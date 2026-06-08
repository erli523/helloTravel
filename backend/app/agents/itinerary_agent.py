"""PlannerAgent implementation — LLM-driven planning with geo-clustering fallback."""

import asyncio
from datetime import timedelta
from typing import Any

from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.agents.geo_day_planner import GeoDayPlanner
from app.agents.hotel_selector import HotelSelector
from app.agents.meal_allocator import MealAllocator
from app.agents.plan_quality_observer import PlanQualityObserver
from app.agents.plan_repairer import PlanRepairer
from app.agents.prompts import PLANNER_AGENT_PROMPT, PLANNER_ITINERARY_PROMPT
from app.agents.route_enricher import RouteEnricher
from app.agents.schedule_builder import ScheduleBuilder
from app.services.budget_service import BudgetService
from app.utils.geo import geo_distance_km
from app.models.travel import (
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    Location,
    Meal,
    ScheduleItem,
    TravelPlanRequest,
    TripPlan,
    WeatherInfo,
)


class PlannerAgent(BaseAgent):
    """
    Integrates specialist Agent outputs into a complete trip plan.

    Planning pipeline:
    1. Ask LLM to assign attractions/meals/hotel intelligently (considers geography,
       weather, ratings, budget).
    2. Fall back to k-means geographic clustering when LLM is unavailable.
    3. Score hotels by rating + proximity to attraction centroid.
    4. Assign meals to the geographically closest candidate for each day.
    5. Enforce budget constraint and append warning when exceeded.
    """

    name = "PlannerAgent"
    prompt_template = PLANNER_AGENT_PROMPT

    def __init__(
        self,
        amap_tools: Any | None = None,
        llm_service: Any | None = None,
        context_bus: Any | None = None,
        budget_service: BudgetService | None = None,
    ) -> None:
        super().__init__(
            amap_tools=amap_tools,
            llm_service=llm_service,
            context_bus=context_bus,
        )
        self.budget_service = budget_service or BudgetService()
        self.schedule_builder = ScheduleBuilder()
        self.geo_day_planner = GeoDayPlanner()
        self.hotel_selector = HotelSelector()
        self.meal_allocator = MealAllocator()
        self.quality_observer = PlanQualityObserver()
        self.plan_repairer = PlanRepairer(
            geo_day_planner=self.geo_day_planner,
            schedule_builder=self.schedule_builder,
            quality_observer=self.quality_observer,
        )
        self.route_enricher = RouteEnricher(
            amap_tools=amap_tools,
            context_bus=context_bus,
            agent_name=self.name,
        )

    def set_context_bus(self, context_bus: Any | None) -> None:
        super().set_context_bus(context_bus)
        self.route_enricher.context_bus = context_bus

    # ── Public entry point ───────────────────────────────────────────────

    async def run(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        weather_info: list[WeatherInfo],
        hotels: list[Hotel],
        meals: list[Meal],
        planner_query: str,
    ) -> AgentResult[TripPlan]:

        days: list[DayPlan] = []
        overall_suggestions = self._default_suggestions(request, weather_info)
        used_llm = False
        setattr(self, "_used_meal_names_cache", set())
        self.meal_allocator.reset()

        # 1. Try LLM-driven planning
        llm_plan = await self._llm_plan_days(request, attractions, weather_info, hotels, meals)
        if llm_plan:
            llm_days, llm_suggestions = self._build_days_from_llm(
                request, attractions, hotels, meals, llm_plan
            )
            if llm_days:
                days = llm_days
                used_llm = True
                if llm_suggestions:
                    overall_suggestions = llm_suggestions

        # 2. Geo-clustering fallback
        if not days:
            days = self._build_days_geo(request, attractions, hotels, meals)
        if self.context_bus is not None:
            self.context_bus.decide(
                agent_name=self.name,
                decision_type="planning_method",
                summary="Selected LLM split planning when usable, otherwise geographic clustering fallback.",
                inputs={
                    "attractions": len(attractions),
                    "hotels": len(hotels),
                    "meals": len(meals),
                    "days": request.days_count,
                },
                outputs={"used_llm": used_llm, "days": len(days)},
            )

        # 3. ReAct planning loop: observe issues, choose actions, then mutate the plan
        days, quality_notes = await self._run_react_planning_loop(
            request,
            days,
            candidate_attractions=attractions,
            candidate_meals=meals,
        )

        # 4. Budget + constraint check
        budget = self.budget_service.calculate(request, days)
        budget_note = self.budget_service.check_constraint(request, budget)
        if budget_note:
            overall_suggestions += f"\n{budget_note}"
        if quality_notes:
            overall_suggestions += "\n行程质量检查：" + "；".join(quality_notes[:5])
        if self.context_bus is not None:
            self.context_bus.result(
                self.name,
                "Final itinerary assembled.",
                total_budget=budget.total,
                days=len(days),
                hotel_nights=budget.hotel_nights,
            )
            self.context_bus.put_artifact(
                "budget",
                {
                    "total": budget.total,
                    "attractions": budget.total_attractions,
                    "hotels": budget.total_hotels,
                    "meals": budget.total_meals,
                    "transportation": budget.total_transportation,
                },
            )

        plan = TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=weather_info,
            overall_suggestions=overall_suggestions,
            budget=budget,
        )

        method = "LLM智能规划（地理+天气+评分）" if used_llm else "地理聚类规划（LLM不可用）"
        reasoning_summary = (
            f"整合景点、天气、酒店、餐饮，通过{method}生成逐天行程并计算分类预算。"
        )
        summary = f"生成 {len(days)} 天行程，预估总预算 {budget.total} 元。"

        return AgentResult(
            data=plan,
            trace=AgentTrace(
                agent_name=self.name,
                prompt=self.prompt_template,
                user_query=planner_query,
                tool_calls=[],
                summary=summary,
                reasoning_summary=reasoning_summary,
                agent_response=overall_suggestions[:300],
                context=self.context_summary(),
            ),
        )

    # ── LLM planning ─────────────────────────────────────────────────────

    async def _llm_plan_days(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        weather_info: list[WeatherInfo],
        hotels: list[Hotel],
        meals: list[Meal],
    ) -> dict[str, Any] | None:
        llm = self.llm_service
        if llm is None or not getattr(llm, "available", False):
            return None

        context = self._format_assignment_context(request, attractions, weather_info, hotels, meals)
        timeout = getattr(getattr(llm, "settings", None), "llm_timeout", 60.0)
        try:
            assignment = None
            for attempt in range(2):
                assignment = await asyncio.wait_for(
                    llm.assign_itinerary_days(
                        system_prompt=self._assignment_prompt(attempt=attempt),
                        planning_context=context,
                    ),
                    timeout=timeout,
                )
                if assignment and len(assignment.get("days") or []) >= request.days_count:
                    break
            if not assignment:
                return None

            schedule_tasks = [
                llm.generate_day_schedule(
                    day_context=self._format_day_schedule_context(
                        request=request,
                        day_data=day_data,
                        attractions=attractions,
                        hotels=hotels,
                        meals=meals,
                        weather_info=weather_info,
                    )
                )
                for day_data in (assignment.get("days") or [])[: request.days_count]
            ]
            if schedule_tasks:
                schedules = await asyncio.wait_for(
                    asyncio.gather(*schedule_tasks, return_exceptions=True),
                    timeout=timeout,
                )
                for day_data, schedule in zip(assignment.get("days") or [], schedules):
                    if isinstance(schedule, list) and schedule:
                        day_data["schedule"] = schedule
            return assignment
        except (asyncio.TimeoutError, Exception):
            return None

    @staticmethod
    def _assignment_prompt(*, attempt: int = 0) -> str:
        retry_note = """
Retry requirement:
- The previous attempt failed or was incomplete.
- You must return all requested days.
- Avoid duplicate attraction complexes and duplicate restaurants across days.
""" if attempt else ""
        return """You are PlannerAgent. Assign attractions, meals, and hotel for a trip.
Return only compact JSON:
{
  "days": [
    {
      "day_index": 0,
      "date": "YYYY-MM-DD",
      "description": "one sentence theme",
      "attraction_names": ["exact candidate attraction name"],
      "lunch_name": "exact candidate meal name or null",
      "dinner_name": "exact candidate meal name or null",
      "weather_note": "brief weather-aware note",
      "day_notes": "route feasibility note"
    }
  ],
  "hotel_name": "exact candidate hotel name or null",
  "overall_suggestions": "100-200 Chinese characters",
  "budget_assessment": "brief budget note"
}
Rules:
- Use only exact names from the candidate lists.
- Keep each day geographically coherent.
- Prefer 2 attractions per day for public transit + walking.
- Do not generate schedule/timeline in this step.""" + retry_note

    def _format_assignment_context(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        weather_info: list[WeatherInfo],
        hotels: list[Hotel],
        meals: list[Meal],
    ) -> str:
        lines: list[str] = []
        preferences = "、".join(request.preferences) or "通用旅游"
        lines += [
            "【用户需求】",
            f"目的地：{request.city}",
            f"日期：{request.start_date} 至 {request.end_date}，共 {request.days_count} 天",
            f"人数：{request.travelers}，预算档次：{request.budget_level}",
            f"偏好：{preferences}，交通：{request.transportation}，住宿：{request.accommodation}",
            "请只做每天的景点/餐厅/酒店分配，不要生成时间轴。",
            "",
            "【候选景点】",
        ]
        for i, att in enumerate(attractions[:14], 1):
            rating = att.rating if att.rating is not None else "暂无"
            lines.append(
                f"{i}. {att.name} | {att.address} | 坐标({att.location.longitude:.4f},{att.location.latitude:.4f}) "
                f"| 类别:{att.category} | 评分:{rating} | 游览:{att.visit_duration}分钟"
            )

        lines.append("")
        lines.append("【天气】")
        for i, w in enumerate(weather_info[: request.days_count], 1):
            lines.append(
                f"第{i}天 {w.date}: {w.day_weather}, {w.day_temp}/{w.night_temp}℃, {w.wind_direction}风{w.wind_power}"
            )

        lines.append("")
        lines.append("【候选酒店】")
        for i, hotel in enumerate(hotels[:8], 1):
            lines.append(f"{i}. {hotel.name} | {hotel.address} | {hotel.price_range} | 评分:{hotel.rating}")

        lines.append("")
        lines.append("【候选餐厅】")
        for i, meal in enumerate(meals[:16], 1):
            addr = meal.address or "地址未知"
            lines.append(f"{i}. {meal.name} | type={meal.type} | {addr} | 人均:{meal.estimated_cost}元")

        return "\n".join(lines)

    def _format_day_schedule_context(
        self,
        *,
        request: TravelPlanRequest,
        day_data: dict[str, Any],
        attractions: list[Attraction],
        hotels: list[Hotel],
        meals: list[Meal],
        weather_info: list[WeatherInfo],
    ) -> str:
        day_index = int(day_data.get("day_index") or 0)
        selected_attractions = [
            att for name in day_data.get("attraction_names") or []
            if (att := self._find_attraction(str(name), attractions)) is not None
        ]
        lunch = self._find_meal_by_name(day_data.get("lunch_name"), meals)
        dinner = self._find_meal_by_name(day_data.get("dinner_name"), meals)
        hotel = self._find_hotel(day_data.get("hotel_name"), hotels) or self._select_best_hotel(hotels, attractions)
        weather = weather_info[day_index] if day_index < len(weather_info) else None

        lines = [
            f"Destination: {request.city}",
            f"Date: {request.start_date + timedelta(days=day_index)}",
            f"Transportation: {request.transportation}",
            f"Theme: {day_data.get('description') or ''}",
            f"Weather: {weather.day_weather if weather else 'unknown'}",
            f"Hotel: {hotel.name if hotel else request.accommodation}",
            "",
            "Selected attractions in route order:",
        ]
        for att in self._order_route(selected_attractions, hotel):
            lines.append(
                f"- {att.name} | {att.address} | visit_duration={att.visit_duration}min "
                f"| coord={att.location.longitude:.4f},{att.location.latitude:.4f}"
            )
        lines += [
            "",
            f"Lunch: {lunch.name if lunch else 'local lunch'} | {lunch.address if lunch else ''}",
            f"Dinner: {dinner.name if dinner else 'local dinner'} | {dinner.address if dinner else ''}",
            "",
            "Return a JSON array only. Include breakfast at 08:30, departure, attractions, lunch, transit/rest, dinner. "
            "Use HH:MM times, no overlaps, no item after 20:00.",
        ]
        return "\n".join(lines)

    def _build_days_from_llm(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        hotels: list[Hotel],
        meals: list[Meal],
        llm_plan: dict[str, Any],
    ) -> tuple[list[DayPlan], str]:
        llm_days: list[dict[str, Any]] = llm_plan.get("days") or []
        if len(llm_days) < request.days_count:
            return [], ""

        selected_hotel = self._find_hotel(
            llm_plan.get("hotel_name"), hotels
        ) or self._select_best_hotel(hotels, attractions)

        plans: list[DayPlan] = []
        used_attractions: set[str] = set()

        for index in range(request.days_count):
            day_data = llm_days[index] if index < len(llm_days) else {}
            date = request.start_date + timedelta(days=index)

            # Resolve attractions by name (with fuzzy matching)
            day_attractions: list[Attraction] = []
            for name in day_data.get("attraction_names") or []:
                att = self._find_attraction(name, attractions)
                if att and att.name not in used_attractions:
                    day_attractions.append(att)
                    used_attractions.add(att.name)
            day_attractions = self._order_route(day_attractions, selected_hotel)

            # Resolve meals
            lunch = self._find_meal_by_name(day_data.get("lunch_name"), meals)
            dinner = self._find_meal_by_name(day_data.get("dinner_name"), meals)
            day_meals = self._assemble_meals(request, lunch, dinner)

            # Build timeline: prefer LLM-generated schedule, fall back to rule-based
            raw_schedule = day_data.get("schedule") or []
            timeline = self._parse_llm_schedule(raw_schedule)
            if not timeline:
                timeline = self._build_default_schedule(request, day_attractions, day_meals)
            timeline = self._fill_schedule_gaps(timeline)

            # Build rich description from LLM fields
            desc_parts: list[str] = []
            if day_data.get("description"):
                desc_parts.append(day_data["description"])
            if day_data.get("weather_note"):
                desc_parts.append(day_data["weather_note"])
            if day_data.get("day_notes"):
                desc_parts.append(day_data["day_notes"])
            description = "。".join(desc_parts) or f"第{index + 1}天游览{request.city}"

            plans.append(DayPlan(
                date=date,
                day_index=index,
                description=description,
                transportation=request.transportation,
                accommodation=(
                    selected_hotel.name if selected_hotel else request.accommodation
                ),
                hotel=selected_hotel,
                attractions=day_attractions,
                meals=day_meals,
                timeline=timeline,
            ))

        # Supplement days that LLM left empty from unused attractions
        unused = [a for a in attractions if a.name not in used_attractions]
        for plan in plans:
            if not plan.attractions and unused:
                plan.attractions = [unused.pop(0)]

        overall = llm_plan.get("overall_suggestions") or ""
        assessment = llm_plan.get("budget_assessment") or ""
        full = "\n".join(p for p in [overall, assessment] if p)
        return plans, full

    # ── Geo-clustering fallback ───────────────────────────────────────────

    def _build_days_geo(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        hotels: list[Hotel],
        meals: list[Meal],
    ) -> list[DayPlan]:
        selected_hotel = self._select_best_hotel(hotels, attractions)
        clusters = self._cluster_attractions(attractions, request.days_count)
        clusters = self._balance_day_clusters(
            clusters,
            max_per_day=self._max_attractions_per_day(request, attractions),
        )

        plans: list[DayPlan] = []
        for index in range(request.days_count):
            date = request.start_date + timedelta(days=index)
            day_atts = self._order_route(
                clusters[index] if index < len(clusters) else [],
                selected_hotel,
            )
            day_meals = self._build_geo_meals(request, meals, day_atts, index)
            plans.append(DayPlan(
                date=date,
                day_index=index,
                description=self._geo_day_description(request, day_atts, index),
                transportation=request.transportation,
                accommodation=(
                    selected_hotel.name if selected_hotel else request.accommodation
                ),
                hotel=selected_hotel,
                attractions=day_atts,
                meals=day_meals,
                timeline=self._fill_schedule_gaps(
                    self._build_default_schedule(request, day_atts, day_meals)
                ),
            ))
        return plans

    def _geo_day_description(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        index: int,
    ) -> str:
        return self.geo_day_planner.day_description(request, attractions, index)

    def _cluster_attractions(
        self,
        attractions: list[Attraction],
        k: int,
    ) -> list[list[Attraction]]:
        return self.geo_day_planner.cluster_attractions(attractions, k)

    def _balance_day_clusters(
        self,
        clusters: list[list[Attraction]],
        max_per_day: int,
    ) -> list[list[Attraction]]:
        return self.geo_day_planner.balance_day_clusters(clusters, max_per_day)

    @staticmethod
    def _max_attractions_per_day(
        request: TravelPlanRequest,
        attractions: list[Attraction],
    ) -> int:
        return GeoDayPlanner.max_attractions_per_day(request, attractions)

    def _order_route(
        self,
        attractions: list[Attraction],
        hotel: Hotel | None = None,
    ) -> list[Attraction]:
        return self.geo_day_planner.order_route(attractions, hotel)

    @staticmethod
    def _geo_distance_km(
        lng1: float,
        lat1: float,
        lng2: float,
        lat2: float,
    ) -> float:
        return geo_distance_km(lng1, lat1, lng2, lat2)

    # ── Meal assignment ───────────────────────────────────────────────────

    def _build_geo_meals(
        self,
        request: TravelPlanRequest,
        meals: list[Meal],
        day_attractions: list[Attraction],
        day_index: int,
    ) -> list[Meal]:
        return self.meal_allocator.build_geo_meals(request, meals, day_attractions)

    def _used_meal_names(self) -> set[str]:
        return self.meal_allocator.used_names

    @staticmethod
    def _pick_unused_meal(meals: list[Meal], used_names: set[str]) -> Meal | None:
        allocator = MealAllocator()
        allocator.used_names = used_names
        return allocator.pick_unused_meal(meals)

    @staticmethod
    def _assemble_meals(
        request: TravelPlanRequest,
        lunch: Meal | None,
        dinner: Meal | None,
    ) -> list[Meal]:
        return MealAllocator.assemble_meals(request, lunch, dinner)

    # ── Hotel selection ───────────────────────────────────────────────────

    def _select_best_hotel(
        self,
        hotels: list[Hotel],
        attractions: list[Attraction],
    ) -> Hotel | None:
        preferred_name = None
        if self.context_bus is not None:
            value = self.context_bus.artifacts.get("preferred_hotel_name")
            preferred_name = str(value) if value else None
        return self.hotel_selector.select_best_hotel(hotels, attractions, preferred_name)

    @staticmethod
    @staticmethod
    def _hotel_rating_float(hotel: Hotel) -> float:
        return HotelSelector.hotel_rating_float(hotel)

    # ── Name-matching helpers (fuzzy) ────────────────────────────────────

    @staticmethod
    def _find_attraction(
        name: str | None, attractions: list[Attraction]
    ) -> Attraction | None:
        if not name:
            return None
        for a in attractions:
            if a.name == name:
                return a
        for a in attractions:
            if name in a.name or a.name in name:
                return a
        return None

    @staticmethod
    @staticmethod
    def _find_hotel(name: str | None, hotels: list[Hotel]) -> Hotel | None:
        return HotelSelector.find_hotel(name, hotels)

    @staticmethod
    def _find_meal_by_name(name: str | None, meals: list[Meal]) -> Meal | None:
        if not name:
            return None
        for m in meals:
            if m.name == name:
                return m
        for m in meals:
            if name in m.name or m.name in name:
                return m
        return None

    # ── Timeline building ─────────────────────────────────────────────────

    @staticmethod
    def _fmt_time(minutes: int) -> str:
        return ScheduleBuilder.fmt_time(minutes)

    @staticmethod
    def _parse_llm_schedule(raw: list[Any]) -> list[ScheduleItem]:
        return ScheduleBuilder.parse_llm_schedule(raw)

    def _build_default_schedule(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        meals: list[Meal],
    ) -> list[ScheduleItem]:
        return self.schedule_builder.build_default_schedule(request, attractions, meals)

    @staticmethod
    def _is_evening_attraction(attraction: Attraction) -> bool:
        return ScheduleBuilder.is_evening_attraction(attraction)

    async def _run_react_planning_loop(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
        *,
        candidate_attractions: list[Attraction] | None = None,
        candidate_meals: list[Meal] | None = None,
    ) -> tuple[list[DayPlan], list[str]]:
        """
        ReAct control loop for final itinerary feasibility.

        The loop observes the current draft, chooses the next repair action, executes
        it, then observes again. This makes ReAct the behavior driver instead of a
        passive trace recorder.
        """

        notes: list[str] = []
        executed_actions: set[str] = set()
        max_iterations = 4

        for iteration in range(max_iterations):
            issues = self._observe_plan_quality(request, days)
            if self.context_bus is not None:
                self.context_bus.observe(
                    self.name,
                    "Observed itinerary draft quality.",
                    iteration=iteration,
                    issues=issues,
                )

            action = await self._choose_react_action_with_llm(
                issues=issues,
                executed_actions=executed_actions,
            )
            if action is None:
                break

            if self.context_bus is not None:
                self.context_bus.think(
                    self.name,
                    "Selected next itinerary repair action from observations.",
                    iteration=iteration,
                    action=action,
                )

            executed_actions.add(action)
            if action == "enrich_routes":
                days = await self._enrich_route_transits(request, days)
                if self.context_bus is not None:
                    self.context_bus.result(
                        self.name,
                        "Route action updated transit blocks with Amap estimates.",
                        iteration=iteration,
                    )
                continue

            if action == "repair_timeline":
                days, repair_notes = self._repair_and_validate_days(request, days)
                notes.extend(repair_notes)
                if self.context_bus is not None:
                    self.context_bus.repair(
                        self.name,
                        "Timeline action repaired overlaps, invalid slots, and idle gaps.",
                        iteration=iteration,
                        quality_notes=repair_notes,
                    )
                continue

            if action == "rebalance_day_load":
                days, rebalance_notes = self._rebalance_overloaded_days(request, days)
                notes.extend(rebalance_notes)
                if self.context_bus is not None:
                    self.context_bus.repair(
                        self.name,
                        "Load action moved excessive public-transit attractions to lighter days.",
                        iteration=iteration,
                        quality_notes=rebalance_notes,
                )
                continue

            if action == "dedupe_attractions":
                days, dedupe_notes = self._dedupe_duplicate_attractions(
                    request,
                    days,
                    candidate_attractions or [],
                )
                notes.extend(dedupe_notes)
                if self.context_bus is not None:
                    self.context_bus.repair(
                        self.name,
                        "Dedupe action replaced repeated attraction complexes with unused candidates.",
                        iteration=iteration,
                        quality_notes=dedupe_notes,
                )
                continue

            if action == "dedupe_meals":
                days, meal_notes = self._dedupe_duplicate_meals(
                    request,
                    days,
                    candidate_meals or [],
                )
                notes.extend(meal_notes)
                if self.context_bus is not None:
                    self.context_bus.repair(
                        self.name,
                        "Meal dedupe action replaced repeated restaurants with unused alternatives.",
                        iteration=iteration,
                        quality_notes=meal_notes,
                    )
                continue

            if action == "fill_sparse_days":
                days, fill_notes = self._fill_sparse_days(
                    request,
                    days,
                    candidate_attractions or [],
                )
                notes.extend(fill_notes)
                if self.context_bus is not None:
                    self.context_bus.repair(
                        self.name,
                        "Sparse-day action added unused attractions to under-filled days.",
                        iteration=iteration,
                        quality_notes=fill_notes,
                    )
                continue

        days, final_notes = self._repair_and_validate_days(request, days)
        notes.extend(final_notes)
        final_issues = self._observe_plan_quality(request, days)
        if self.context_bus is not None:
            self.context_bus.result(
                self.name,
                "ReAct loop finalized itinerary quality state.",
                executed_actions=list(executed_actions),
                remaining_issues=final_issues,
            )
        notes.extend(
            self._quality_notes_from_issues(
                issue for issue in final_issues if issue.get("severity") != "info"
            )
        )
        return days, list(dict.fromkeys(notes))

    def _observe_plan_quality(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
    ) -> list[dict[str, Any]]:
        return self.quality_observer.observe(
            request,
            days,
            has_route_tools=self.amap_tools is not None,
            max_day_leg_km=self._max_day_leg_km,
        )

    @staticmethod
    def _choose_react_action(
        issues: list[dict[str, Any]],
        executed_actions: set[str],
    ) -> str | None:
        priority = [
            "dedupe_attractions",
            "dedupe_meals",
            "enrich_routes",
            "repair_timeline",
            "rebalance_day_load",
            "fill_sparse_days",
        ]
        observed_actions = {str(issue.get("action")) for issue in issues}
        for action in priority:
            if action in observed_actions and action not in executed_actions:
                return action
        return None

    async def _choose_react_action_with_llm(
        self,
        *,
        issues: list[dict[str, Any]],
        executed_actions: set[str],
    ) -> str | None:
        if not issues:
            return None

        rule_action = self._choose_react_action(issues, executed_actions)
        if rule_action is not None:
            return rule_action

        available_actions = [
            action
            for action in [
                "dedupe_attractions",
                "dedupe_meals",
                "enrich_routes",
                "repair_timeline",
                "rebalance_day_load",
                "fill_sparse_days",
            ]
            if action not in executed_actions
        ]
        if not available_actions:
            return None

        llm = self.llm_service
        if llm is not None and getattr(llm, "available", False):
            try:
                action = await asyncio.wait_for(
                    llm.choose_react_action(
                        issues=[
                            issue for issue in issues
                            if issue.get("action") in available_actions
                        ],
                        available_actions=available_actions,
                        executed_actions=sorted(executed_actions),
                    ),
                    timeout=getattr(llm.settings, "agent_response_timeout", 20.0),
                )
                if action in available_actions:
                    return action
            except (AttributeError, asyncio.TimeoutError):
                pass

        return self._choose_react_action(issues, executed_actions)

    def _day_has_unestimated_transit(self, day: DayPlan) -> bool:
        return self.quality_observer.day_has_unestimated_transit(day)

    def _rebalance_overloaded_days(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
    ) -> tuple[list[DayPlan], list[str]]:
        return self.plan_repairer.rebalance_overloaded_days(request, days)

    @staticmethod
    def _find_lighter_day_index(days: list[DayPlan], *, exclude: int) -> int | None:
        return PlanRepairer.find_lighter_day_index(days, exclude=exclude)

    def _fill_sparse_days(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
        candidate_attractions: list[Attraction] | None = None,
    ) -> tuple[list[DayPlan], list[str]]:
        return self.plan_repairer.fill_sparse_days(request, days, candidate_attractions)

    def _dedupe_duplicate_attractions(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
        candidate_attractions: list[Attraction],
    ) -> tuple[list[DayPlan], list[str]]:
        return self.plan_repairer.dedupe_duplicate_attractions(
            request,
            days,
            candidate_attractions,
        )

    def _dedupe_duplicate_meals(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
        candidate_meals: list[Meal],
    ) -> tuple[list[DayPlan], list[str]]:
        return self.plan_repairer.dedupe_duplicate_meals(request, days, candidate_meals)

    @staticmethod
    def _find_unused_meal_candidate(
        duplicate_meal: Meal,
        candidate_meals: list[Meal],
        used_names: set[str],
    ) -> Meal | None:
        return PlanRepairer.find_unused_meal_candidate(
            duplicate_meal,
            candidate_meals,
            used_names,
        )

    def _build_local_experience_candidate(
        self,
        request: TravelPlanRequest,
        day: DayPlan,
        offset_index: int,
    ) -> Attraction | None:
        return self.plan_repairer.build_local_experience_candidate(
            request,
            day,
            offset_index,
        )

    def _find_unused_candidate_for_day(
        self,
        day: DayPlan,
        used_attractions: list[Attraction],
        candidate_attractions: list[Attraction],
    ) -> Attraction | None:
        return self.plan_repairer.find_unused_candidate_for_day(
            day,
            used_attractions,
            candidate_attractions,
        )

    def _cross_day_duplicate_issues(self, days: list[DayPlan]) -> list[dict[str, Any]]:
        return self.quality_observer.cross_day_duplicate_issues(days)

    @staticmethod
    def _duplicate_meal_issues(days: list[DayPlan]) -> list[dict[str, Any]]:
        return PlanQualityObserver.duplicate_meal_issues(days)

    def _same_attraction_complex(self, first: Attraction, second: Attraction) -> bool:
        return self.quality_observer.same_attraction_complex(first, second)

    @staticmethod
    def _canonical_attraction_name(name: str) -> str:
        return PlanQualityObserver.canonical_attraction_name(name)

    @staticmethod
    def _schedule_item_looks_evening(item: ScheduleItem) -> bool:
        return PlanQualityObserver.schedule_item_looks_evening(item)

    @staticmethod
    def _quality_notes_from_issues(issues: Any) -> list[str]:
        return PlanQualityObserver.quality_notes_from_issues(issues)

    async def _enrich_route_transits(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
    ) -> list[DayPlan]:
        self.route_enricher.amap_tools = self.amap_tools
        self.route_enricher.context_bus = self.context_bus
        return await self.route_enricher.enrich_route_transits(request, days)

    async def _enrich_day_transits(
        self,
        request: TravelPlanRequest,
        day: DayPlan,
    ) -> list[ScheduleItem]:
        self.route_enricher.amap_tools = self.amap_tools
        self.route_enricher.context_bus = self.context_bus
        return await self.route_enricher.enrich_day_transits(request, day)

    @staticmethod
    def _nearest_timeline_attraction(
        timeline: list[ScheduleItem],
        attractions_by_name: dict[str, Attraction],
        *,
        start: int,
        step: int,
    ) -> Attraction | None:
        return RouteEnricher.nearest_timeline_attraction(
            timeline,
            attractions_by_name,
            start=start,
            step=step,
        )

    @staticmethod
    def _match_timeline_attraction(
        item: ScheduleItem,
        attractions_by_name: dict[str, Attraction],
    ) -> Attraction | None:
        return RouteEnricher.match_timeline_attraction(item, attractions_by_name)

    async def _route_estimate(
        self,
        request: TravelPlanRequest,
        origin: Attraction,
        destination: Attraction,
    ) -> tuple[int, float, str] | None:
        self.route_enricher.amap_tools = self.amap_tools
        return await self.route_enricher.route_estimate(request, origin, destination)

    def _route_cache(self) -> dict[tuple[str, str, str, str], tuple[int, float, str]]:
        return self.route_enricher.cache

    @staticmethod
    def _coord(location: Any) -> str:
        return RouteEnricher.coord(location)

    def _parse_route_result(
        self,
        result: Any,
        *,
        fallback_distance_km: float,
    ) -> tuple[int, float] | None:
        return self.route_enricher.parse_route_result(
            result,
            fallback_distance_km=fallback_distance_km,
        )

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        return RouteEnricher.safe_float(value)

    @staticmethod
    def _parse_time_minutes(value: str) -> int | None:
        return ScheduleBuilder.parse_time_minutes(value)

    def _normalize_schedule(self, schedule: list[ScheduleItem]) -> list[ScheduleItem]:
        return self.schedule_builder.normalize_schedule(schedule)

    def _fill_schedule_gaps(self, schedule: list[ScheduleItem]) -> list[ScheduleItem]:
        return self.schedule_builder.fill_schedule_gaps(schedule)

    def _repair_and_validate_days(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
    ) -> tuple[list[DayPlan], list[str]]:
        return self.schedule_builder.repair_and_validate_days(
            request,
            days,
            self._max_day_leg_km,
        )

    def _repair_timeline(
        self,
        timeline: list[ScheduleItem],
    ) -> tuple[list[ScheduleItem], list[str]]:
        return self.schedule_builder.repair_timeline(timeline)

    def _max_day_leg_km(self, attractions: list[Attraction]) -> float:
        return self.geo_day_planner.max_day_leg_km(attractions)

    def _calculate_budget(
        self, request: TravelPlanRequest, days: list[DayPlan]
    ) -> Budget:
        return self.budget_service.calculate(request, days)

    @staticmethod
    def _transport_unit_cost(request: TravelPlanRequest) -> int:
        return BudgetService.transport_unit_cost(request)

    @staticmethod
    def _check_budget(request: TravelPlanRequest, budget: Budget) -> str:
        return BudgetService.check_constraint(request, budget)

    # ── Default suggestions (when LLM unavailable) ───────────────────────

    @staticmethod
    def _default_suggestions(
        request: TravelPlanRequest,
        weather_info: list[WeatherInfo],
    ) -> str:
        lines = [f"欢迎前往{request.city}！以下是出行贴士："]
        rainy = [w for w in weather_info if "雨" in w.day_weather or "阴" in w.day_weather]
        if rainy:
            dates = "、".join(str(w.date) for w in rainy)
            lines.append(f"预计{dates}天气较差，建议携带雨具或将户外景点调整为室内场所。")
        if weather_info:
            max_temp = max(w.day_temp for w in weather_info)
            min_temp = min(w.night_temp for w in weather_info)
            if max_temp >= 30:
                lines.append(f"旅途中白天最高气温约{max_temp}℃，注意防晒补水。")
            if min_temp <= 10:
                lines.append(f"夜间最低气温约{min_temp}℃，建议携带外套保暖。")
        lines.append("每天预留1-2小时弹性时间，出发前确认景点开放时间及预约要求。")
        return "\n".join(lines)


# Backward-compatible alias.
ItineraryAgent = PlannerAgent
