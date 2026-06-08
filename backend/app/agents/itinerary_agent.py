"""PlannerAgent implementation — LLM-driven planning with geo-clustering fallback."""

import asyncio
from datetime import timedelta
from typing import Any

from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.agents.prompts import PLANNER_AGENT_PROMPT, PLANNER_ITINERARY_PROMPT
from app.models.travel import (
    Attraction,
    Budget,
    BudgetDetail,
    DayPlan,
    Hotel,
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
        days, quality_notes = await self._run_react_planning_loop(request, days)

        # 4. Budget + constraint check
        budget = self._calculate_budget(request, days)
        budget_note = self._check_budget(request, budget)
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
            assignment = await asyncio.wait_for(
                llm.assign_itinerary_days(
                    system_prompt=self._assignment_prompt(),
                    planning_context=context,
                ),
                timeout=timeout,
            )
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
    def _assignment_prompt() -> str:
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
- Do not generate schedule/timeline in this step."""

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
                description=(
                    f"第{index + 1}天：{'探索' + request.city + '精华景点' if index == 0 else '继续游览' + request.city + '更多风光'}"
                ),
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

    def _cluster_attractions(
        self,
        attractions: list[Attraction],
        k: int,
    ) -> list[list[Attraction]]:
        """Group attractions by geographic proximity using k-means."""
        if not attractions or k <= 0:
            return [[] for _ in range(k)]
        if k >= len(attractions):
            clusters = [[att] for att in attractions]
            clusters += [[] for _ in range(k - len(attractions))]
            return clusters

        # Initial centroids: evenly spaced through spatially sorted list
        sorted_atts = sorted(
            attractions,
            key=lambda a: a.location.longitude + a.location.latitude,
        )
        step = len(sorted_atts) / k
        centroids: list[tuple[float, float]] = [
            (
                sorted_atts[int(i * step)].location.longitude,
                sorted_atts[int(i * step)].location.latitude,
            )
            for i in range(k)
        ]

        clusters: list[list[Attraction]] = [[] for _ in range(k)]
        for _ in range(10):
            new_clusters: list[list[Attraction]] = [[] for _ in range(k)]
            for att in attractions:
                nearest = min(
                    range(k),
                    key=lambda ci: (
                        (att.location.longitude - centroids[ci][0]) ** 2
                        + (att.location.latitude - centroids[ci][1]) ** 2
                    ),
                )
                new_clusters[nearest].append(att)

            # Update centroids; detect convergence
            changed = False
            for i, cluster in enumerate(new_clusters):
                if not cluster:
                    continue
                nlng = sum(a.location.longitude for a in cluster) / len(cluster)
                nlat = sum(a.location.latitude for a in cluster) / len(cluster)
                if (nlng, nlat) != centroids[i]:
                    centroids[i] = (nlng, nlat)
                    changed = True

            clusters = new_clusters
            if not changed:
                break

        # Redistribute from largest cluster to empty ones
        for i, cluster in enumerate(clusters):
            if not cluster:
                largest = max(range(k), key=lambda j: len(clusters[j]))
                if len(clusters[largest]) > 1:
                    clusters[i] = [clusters[largest].pop()]

        # Order clusters west→east for a natural day progression
        order = sorted(
            range(k),
            key=lambda i: (
                sum(a.location.longitude for a in clusters[i]) / max(len(clusters[i]), 1)
            ),
        )
        return [clusters[i] for i in order]

    def _balance_day_clusters(
        self,
        clusters: list[list[Attraction]],
        max_per_day: int,
    ) -> list[list[Attraction]]:
        """Keep each day small enough to fit the time schedule."""

        if max_per_day <= 0:
            return clusters

        changed = True
        while changed:
            changed = False
            oversized = [
                index for index, cluster in enumerate(clusters)
                if len(cluster) > max_per_day
            ]
            if not oversized:
                break

            for source_index in oversized:
                source = clusters[source_index]
                while len(source) > max_per_day:
                    target_index = min(
                        range(len(clusters)),
                        key=lambda i: (len(clusters[i]), i == source_index),
                    )
                    if target_index == source_index:
                        break
                    clusters[target_index].append(source.pop())
                    changed = True
        return clusters

    @staticmethod
    def _max_attractions_per_day(
        request: TravelPlanRequest,
        attractions: list[Attraction],
    ) -> int:
        if request.transportation == "public transit + walking":
            return 2
        if any(att.visit_duration >= 150 for att in attractions):
            return 2
        return 3

    def _order_route(
        self,
        attractions: list[Attraction],
        hotel: Hotel | None = None,
    ) -> list[Attraction]:
        """Order a day's attractions by nearest-neighbor distance."""

        if len(attractions) <= 1:
            return attractions

        remaining = attractions[:]
        ordered: list[Attraction] = []
        if hotel and hotel.location:
            current_lng = hotel.location.longitude
            current_lat = hotel.location.latitude
            first = min(
                remaining,
                key=lambda att: self._geo_distance_km(
                    current_lng,
                    current_lat,
                    att.location.longitude,
                    att.location.latitude,
                ),
            )
        else:
            first = min(
                remaining,
                key=lambda att: (att.location.longitude, att.location.latitude),
            )

        ordered.append(first)
        remaining.remove(first)
        while remaining:
            current = ordered[-1]
            nxt = min(
                remaining,
                key=lambda att: self._geo_distance_km(
                    current.location.longitude,
                    current.location.latitude,
                    att.location.longitude,
                    att.location.latitude,
                ),
            )
            ordered.append(nxt)
            remaining.remove(nxt)
        return ordered

    @staticmethod
    def _geo_distance_km(
        lng1: float,
        lat1: float,
        lng2: float,
        lat2: float,
    ) -> float:
        """Approximate great-circle distance in kilometers."""

        import math

        radius = 6371.0
        lat1_r = math.radians(lat1)
        lat2_r = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        h = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
        )
        return radius * 2 * math.asin(math.sqrt(h))

    # ── Meal assignment ───────────────────────────────────────────────────

    def _build_geo_meals(
        self,
        request: TravelPlanRequest,
        meals: list[Meal],
        day_attractions: list[Attraction],
        day_index: int,
    ) -> list[Meal]:
        """Select meals geographically closest to the day's attractions."""
        if day_attractions:
            clng = sum(a.location.longitude for a in day_attractions) / len(day_attractions)
            clat = sum(a.location.latitude for a in day_attractions) / len(day_attractions)

            def dist(m: Meal) -> float:
                if m.location is None:
                    return 999.0
                return (
                    (m.location.longitude - clng) ** 2
                    + (m.location.latitude - clat) ** 2
                ) ** 0.5
        else:
            def dist(_: Meal) -> float:
                return 0.0

        lunches = sorted(
            [m for m in meals if m.type in ("lunch", "snack")], key=dist
        )
        dinners = sorted(
            [m for m in meals if m.type == "dinner"], key=dist
        )
        lunch = lunches[day_index % len(lunches)] if lunches else None
        dinner = dinners[day_index % len(dinners)] if dinners else None
        return self._assemble_meals(request, lunch, dinner)

    @staticmethod
    def _assemble_meals(
        request: TravelPlanRequest,
        lunch: Meal | None,
        dinner: Meal | None,
    ) -> list[Meal]:
        return [
            Meal(
                type="breakfast",
                name="酒店早餐",
                description="出发前在酒店享用早餐，为一天的游览储备能量。",
                estimated_cost=40,
            ),
            (
                lunch.model_copy(update={"type": "lunch"})
                if lunch
                else Meal(
                    type="lunch",
                    name=f"{request.city}特色午餐",
                    description="就近选择当地特色餐厅享用午餐。",
                    estimated_cost=80,
                )
            ),
            (
                dinner.model_copy(update={"type": "dinner"})
                if dinner
                else Meal(
                    type="dinner",
                    name=f"{request.city}招牌晚餐",
                    description="在交通便利处品尝当地招牌美食。",
                    estimated_cost=120,
                )
            ),
        ]

    # ── Hotel selection ───────────────────────────────────────────────────

    def _select_best_hotel(
        self,
        hotels: list[Hotel],
        attractions: list[Attraction],
    ) -> Hotel | None:
        if not hotels:
            return None
        if self.context_bus is not None:
            preferred_name = self.context_bus.artifacts.get("preferred_hotel_name")
            preferred_hotel = self._find_hotel(
                str(preferred_name) if preferred_name else None,
                hotels,
            )
            if preferred_hotel is not None:
                return preferred_hotel
        if not attractions:
            return max(hotels, key=self._hotel_rating_float)

        # Compute attraction centroid
        clng = sum(a.location.longitude for a in attractions) / len(attractions)
        clat = sum(a.location.latitude for a in attractions) / len(attractions)

        def score(hotel: Hotel) -> float:
            rating_score = self._hotel_rating_float(hotel) / 5.0
            if hotel.location is not None:
                dist = (
                    (hotel.location.longitude - clng) ** 2
                    + (hotel.location.latitude - clat) ** 2
                ) ** 0.5
                # Typical intra-city scale ~0.15 degree ≈ 15 km
                proximity = max(0.0, 1.0 - dist / 0.15)
            else:
                proximity = 0.3
            return rating_score * 0.4 + proximity * 0.6

        return max(hotels, key=score)

    @staticmethod
    def _hotel_rating_float(hotel: Hotel) -> float:
        try:
            return float(hotel.rating)
        except (ValueError, TypeError):
            return 3.5

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
    def _find_hotel(name: str | None, hotels: list[Hotel]) -> Hotel | None:
        if not name:
            return None
        for h in hotels:
            if h.name == name:
                return h
        for h in hotels:
            if name in h.name or h.name in name:
                return h
        return None

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
        """Convert minutes-from-midnight to HH:MM string."""
        h = (minutes // 60) % 24
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    @staticmethod
    def _parse_llm_schedule(raw: list[Any]) -> list[ScheduleItem]:
        """Parse the schedule array returned by the LLM, tolerating bad fields."""
        result: list[ScheduleItem] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                result.append(ScheduleItem(
                    time=str(item.get("time") or ""),
                    end_time=str(item.get("end_time") or ""),
                    activity=str(item.get("activity") or ""),
                    location=str(item.get("location") or ""),
                    notes=str(item.get("notes") or ""),
                    item_type=str(
                        item.get("item_type") or item.get("type") or "attraction"
                    ),
                ))
            except Exception:
                continue
        return result

    def _build_default_schedule(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        meals: list[Meal],
    ) -> list[ScheduleItem]:
        """
        Build a rule-based time schedule from 08:30 to 20:00.

        Used when the LLM does not return a schedule (or as a fallback for the
        geo-clustering path). Assigns realistic transit time between attractions
        based on geographic distance, and ensures lunch/dinner fall in the
        expected windows.
        """
        schedule: list[ScheduleItem] = []
        current = 10 * 60  # 10:00 in minutes

        breakfast = next((m for m in meals if m.type == "breakfast"), None)
        lunch = next((m for m in meals if m.type == "lunch"), None)
        dinner = next((m for m in meals if m.type == "dinner"), None)

        # 08:30 — Breakfast
        if breakfast:
            schedule.append(ScheduleItem(
                time="08:30",
                end_time="09:30",
                activity=f"早餐：{breakfast.name}",
                location="酒店",
                notes="在酒店享用早餐，为一天游览储备能量。",
                item_type="meal",
            ))

        # 09:30 — Depart
        schedule.append(ScheduleItem(
            time="09:30",
            end_time="10:00",
            activity="整理行装，出发前往景区",
            location="",
            notes="确认景点开放时间及预约情况，规划当天最优路线。",
            item_type="transit",
        ))

        lunch_inserted = False
        sorted_atts = attractions

        for i, att in enumerate(sorted_atts):
            # Insert lunch when the clock hits 12:00
            if not lunch_inserted and current >= 12 * 60:
                ls, le = current, current + 90
                schedule.append(ScheduleItem(
                    time=self._fmt_time(ls),
                    end_time=self._fmt_time(le),
                    activity=f"午餐：{lunch.name if lunch else request.city + '特色午餐'}",
                    location=(lunch.address or "") if lunch else "",
                    notes="就近选择特色餐厅，享用午餐后稍作休息。",
                    item_type="meal",
                ))
                lunch_inserted = True
                current = le

            # Stop if can't fit attraction before dinner slot
            if current + att.visit_duration > 18 * 60:
                if not lunch_inserted:
                    ls = max(current, 12 * 60)
                    schedule.append(ScheduleItem(
                        time=self._fmt_time(ls),
                        end_time=self._fmt_time(ls + 90),
                        activity=f"午餐：{lunch.name if lunch else request.city + '特色午餐'}",
                        location=(lunch.address or "") if lunch else "",
                        notes="享用午餐，稍作休息。",
                        item_type="meal",
                    ))
                    lunch_inserted = True
                remaining = [a.name for a in sorted_atts[i : i + 2]]
                schedule.append(ScheduleItem(
                    time=self._fmt_time(max(current, 16 * 60)),
                    end_time="18:00",
                    activity="自由活动 / 特色街区闲逛",
                    location="",
                    notes=(
                        "今日行程较为充实，可在附近特色街区放松游逛。"
                        + (
                            f"「{'、'.join(remaining)}」等景点建议安排至其他天。"
                            if remaining
                            else ""
                        )
                    ),
                    item_type="rest",
                ))
                break

            # Attraction block
            schedule.append(ScheduleItem(
                time=self._fmt_time(current),
                end_time=self._fmt_time(current + att.visit_duration),
                activity=f"游览：{att.name}",
                location=att.name,
                notes=(
                    f"建议游览约 {att.visit_duration} 分钟"
                    + (
                        f"，门票 {att.ticket_price} 元/人"
                        if att.ticket_price > 0
                        else "，免费开放"
                    )
                    + (f"，综合评分 {att.rating} 分" if att.rating else "")
                    + "。"
                ),
                item_type="attraction",
            ))
            current += att.visit_duration

            # Estimate transit to next attraction from geographic distance
            if i < len(sorted_atts) - 1:
                next_att = sorted_atts[i + 1]
                dist_km = self._geo_distance_km(
                    att.location.longitude,
                    att.location.latitude,
                    next_att.location.longitude,
                    next_att.location.latitude,
                )
                if dist_km < 1:
                    transit_min, transit_note = 10, "步行约 10 分钟可达。"
                elif dist_km < 4:
                    transit_min, transit_note = 20, "步行或骑行约 20 分钟可达。"
                elif dist_km < 12:
                    transit_min, transit_note = 35, "乘坐公交 / 地铁约 30-40 分钟可达。"
                else:
                    transit_min, transit_note = 50, "乘坐地铁约 40-50 分钟可达。"

                if current + transit_min < 18 * 60:
                    schedule.append(ScheduleItem(
                        time=self._fmt_time(current),
                        end_time=self._fmt_time(current + transit_min),
                        activity=f"前往{next_att.name}",
                        location="",
                        notes=transit_note,
                        item_type="transit",
                    ))
                    current += transit_min

        # Insert lunch if it still hasn't appeared (e.g., only 1 short attraction)
        if not lunch_inserted:
            ls = max(current, 12 * 60)
            le = ls + 90
            if le <= 20 * 60:
                schedule.append(ScheduleItem(
                    time=self._fmt_time(ls),
                    end_time=self._fmt_time(le),
                    activity=f"午餐：{lunch.name if lunch else request.city + '特色午餐'}",
                    location=(lunch.address or "") if lunch else "",
                    notes="享用午餐。",
                    item_type="meal",
                ))
                current = le

        # Dinner ~18:00
        dinner_start = max(current, 18 * 60)
        if dinner_start < 20 * 60:
            schedule.append(ScheduleItem(
                time=self._fmt_time(dinner_start),
                end_time=self._fmt_time(min(dinner_start + 90, 20 * 60)),
                activity=f"晚餐：{dinner.name if dinner else request.city + '招牌晚餐'}",
                location=(dinner.address or "") if dinner else "",
                notes="品尝当地招牌美食，结束一天的精彩行程。",
                item_type="meal",
            ))

        return self._fill_schedule_gaps(schedule)

    async def _run_react_planning_loop(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
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
        issues: list[dict[str, Any]] = []
        for day in days:
            timeline = self._normalize_schedule(day.timeline)
            if len(timeline) != len(day.timeline):
                issues.append(
                    {
                        "code": "invalid_timeline",
                        "severity": "high",
                        "day_index": day.day_index,
                        "action": "repair_timeline",
                    }
                )

            for first, second in zip(timeline, timeline[1:]):
                first_end = self._parse_time_minutes(first.end_time)
                second_start = self._parse_time_minutes(second.time)
                if first_end is not None and second_start is not None:
                    gap = second_start - first_end
                    if gap < 0:
                        issues.append(
                            {
                                "code": "timeline_overlap",
                                "severity": "high",
                                "day_index": day.day_index,
                                "action": "repair_timeline",
                            }
                        )
                    elif gap >= 120:
                        issues.append(
                            {
                                "code": "long_idle_gap",
                                "severity": "medium",
                                "day_index": day.day_index,
                                "minutes": gap,
                                "action": "repair_timeline",
                            }
                        )

            if self.amap_tools is not None and self._day_has_unestimated_transit(day):
                issues.append(
                    {
                        "code": "missing_route_estimate",
                        "severity": "medium",
                        "day_index": day.day_index,
                        "action": "enrich_routes",
                    }
                )

            if (
                request.transportation == "public transit + walking"
                and len(day.attractions) > 3
            ):
                issues.append(
                    {
                        "code": "overloaded_public_transit_day",
                        "severity": "medium",
                        "day_index": day.day_index,
                        "count": len(day.attractions),
                        "action": "rebalance_day_load",
                    }
                )

            max_leg = self._max_day_leg_km(day.attractions)
            if max_leg > 18 and request.transportation == "public transit + walking":
                issues.append(
                    {
                        "code": "cross_district_leg",
                        "severity": "medium",
                        "day_index": day.day_index,
                        "distance_km": round(max_leg, 1),
                        "action": "rebalance_day_load",
                    }
                )

            meal_types = {meal.type for meal in day.meals}
            if "lunch" not in meal_types:
                issues.append(
                    {
                        "code": "missing_lunch",
                        "severity": "info",
                        "day_index": day.day_index,
                        "action": "note",
                    }
                )
            if "dinner" not in meal_types:
                issues.append(
                    {
                        "code": "missing_dinner",
                        "severity": "info",
                        "day_index": day.day_index,
                        "action": "note",
                    }
                )

        return issues

    @staticmethod
    def _choose_react_action(
        issues: list[dict[str, Any]],
        executed_actions: set[str],
    ) -> str | None:
        priority = ["enrich_routes", "repair_timeline", "rebalance_day_load"]
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
            for action in ["enrich_routes", "repair_timeline", "rebalance_day_load"]
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
        if len(day.attractions) < 2:
            return False
        by_name = {att.name: att for att in day.attractions}
        for index, item in enumerate(day.timeline):
            if item.item_type != "transit":
                continue
            if "高德" in item.notes or "Amap" in item.notes:
                continue
            previous_attraction = self._nearest_timeline_attraction(
                day.timeline,
                by_name,
                start=index - 1,
                step=-1,
            )
            next_attraction = self._nearest_timeline_attraction(
                day.timeline,
                by_name,
                start=index + 1,
                step=1,
            )
            if previous_attraction is not None and next_attraction is not None:
                return True
        return False

    def _rebalance_overloaded_days(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
    ) -> tuple[list[DayPlan], list[str]]:
        if request.transportation != "public transit + walking" or len(days) < 2:
            return days, []

        notes: list[str] = []
        mutable_days = list(days)
        for index, day in enumerate(list(mutable_days)):
            if len(day.attractions) <= 3:
                continue
            receiver_index = self._find_lighter_day_index(mutable_days, exclude=index)
            if receiver_index is None:
                continue
            moved = day.attractions[-1]
            source_attractions = day.attractions[:-1]
            receiver = mutable_days[receiver_index]
            receiver_attractions = receiver.attractions + [moved]

            mutable_days[index] = day.model_copy(
                update={
                    "attractions": source_attractions,
                    "timeline": self._fill_schedule_gaps(
                        self._build_default_schedule(request, source_attractions, day.meals)
                    ),
                }
            )
            mutable_days[receiver_index] = receiver.model_copy(
                update={
                    "attractions": receiver_attractions,
                    "timeline": self._fill_schedule_gaps(
                        self._build_default_schedule(
                            request,
                            receiver_attractions,
                            receiver.meals,
                        )
                    ),
                }
            )
            notes.append(
                f"Moved {moved.name} from day {day.day_index + 1} to day "
                f"{receiver.day_index + 1} to reduce public-transit load"
            )

        return mutable_days, notes

    @staticmethod
    def _find_lighter_day_index(days: list[DayPlan], *, exclude: int) -> int | None:
        candidates = [
            (index, len(day.attractions))
            for index, day in enumerate(days)
            if index != exclude and len(day.attractions) < 3
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[1])[0]

    @staticmethod
    def _quality_notes_from_issues(issues: Any) -> list[str]:
        notes: list[str] = []
        for issue in issues:
            day = int(issue.get("day_index", 0)) + 1
            code = issue.get("code")
            if code == "cross_district_leg":
                notes.append(f"Day {day} still has a long cross-district transfer.")
            elif code == "overloaded_public_transit_day":
                notes.append(f"Day {day} remains dense for public transit.")
            elif code == "missing_route_estimate":
                notes.append(f"Day {day} has a transit segment without live route estimate.")
            elif code == "timeline_overlap":
                notes.append(f"Day {day} still has a timeline overlap.")
        return notes

    async def _enrich_route_transits(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
    ) -> list[DayPlan]:
        """Use Amap route tools to correct transit notes when coordinates are known."""

        if self.amap_tools is None:
            return days

        enriched_days: list[DayPlan] = []
        for day in days:
            timeline = await self._enrich_day_transits(request, day)
            enriched_days.append(day.model_copy(update={"timeline": timeline}))
        return enriched_days

    async def _enrich_day_transits(
        self,
        request: TravelPlanRequest,
        day: DayPlan,
    ) -> list[ScheduleItem]:
        if not day.timeline or len(day.attractions) < 2:
            return day.timeline

        by_name = {att.name: att for att in day.attractions}
        updated: list[ScheduleItem] = []
        for index, item in enumerate(day.timeline):
            if item.item_type != "transit":
                updated.append(item)
                continue

            previous_attraction = self._nearest_timeline_attraction(
                day.timeline,
                by_name,
                start=index - 1,
                step=-1,
            )
            next_attraction = self._nearest_timeline_attraction(
                day.timeline,
                by_name,
                start=index + 1,
                step=1,
            )
            if previous_attraction is None or next_attraction is None:
                updated.append(item)
                continue

            estimate = await self._route_estimate(
                request,
                previous_attraction,
                next_attraction,
            )
            if estimate is None:
                updated.append(item)
                continue

            duration_min, distance_km, mode_note = estimate
            if self.context_bus is not None:
                self.context_bus.act(
                    self.name,
                    "Queried route estimate for adjacent itinerary stops.",
                    origin=previous_attraction.name,
                    destination=next_attraction.name,
                    duration_min=duration_min,
                    distance_km=round(distance_km, 2),
                )
            start = self._parse_time_minutes(item.time)
            next_start = self._parse_time_minutes(
                day.timeline[index + 1].time if index + 1 < len(day.timeline) else ""
            )
            if start is None:
                updated.append(item)
                continue

            end = start + max(5, duration_min)
            if next_start is not None:
                end = min(end, next_start)
            updated.append(
                item.model_copy(
                    update={
                        "end_time": self._fmt_time(end),
                        "activity": f"前往{next_attraction.name}",
                        "location": f"{previous_attraction.name} -> {next_attraction.name}",
                        "notes": (
                            f"{mode_note}，高德路线估算约 {duration_min} 分钟，"
                            f"距离约 {distance_km:.1f} 公里。"
                        ),
                    }
                )
            )

        return self._fill_schedule_gaps(updated)

    @staticmethod
    def _nearest_timeline_attraction(
        timeline: list[ScheduleItem],
        attractions_by_name: dict[str, Attraction],
        *,
        start: int,
        step: int,
    ) -> Attraction | None:
        index = start
        while 0 <= index < len(timeline):
            item = timeline[index]
            if item.item_type == "attraction":
                attraction = PlannerAgent._match_timeline_attraction(item, attractions_by_name)
                if attraction is not None:
                    return attraction
            index += step
        return None

    @staticmethod
    def _match_timeline_attraction(
        item: ScheduleItem,
        attractions_by_name: dict[str, Attraction],
    ) -> Attraction | None:
        candidates = [item.location, item.activity]
        for value in candidates:
            if value in attractions_by_name:
                return attractions_by_name[value]
        text = " ".join(candidates)
        for name, attraction in attractions_by_name.items():
            if name and name in text:
                return attraction
        return None

    async def _route_estimate(
        self,
        request: TravelPlanRequest,
        origin: Attraction,
        destination: Attraction,
    ) -> tuple[int, float, str] | None:
        if self.amap_tools is None:
            return None

        distance_km = self._geo_distance_km(
            origin.location.longitude,
            origin.location.latitude,
            destination.location.longitude,
            destination.location.latitude,
        )
        if request.transportation == "public transit + walking":
            tool_name = (
                "amap_maps_direction_walking"
                if distance_km <= 1.5
                else "amap_maps_direction_transit_integrated"
            )
        else:
            tool_name = "amap_maps_direction_driving"

        cache_key = (
            self._coord(origin.location),
            self._coord(destination.location),
            tool_name,
            request.city,
        )
        route_cache = self._route_cache()
        if cache_key in route_cache:
            return route_cache[cache_key]

        result = await self.amap_tools.call_tool(
            tool_name,
            {
                "origin": self._coord(origin.location),
                "destination": self._coord(destination.location),
                "city": request.city,
            },
        )
        estimate = self._parse_route_result(result.get("result"), fallback_distance_km=distance_km)
        if estimate is None:
            return None

        duration_min, route_distance_km = estimate
        if tool_name == "amap_maps_direction_walking":
            mode_note = "步行衔接"
        elif tool_name == "amap_maps_direction_driving":
            mode_note = "驾车/打车衔接"
        else:
            mode_note = "公交/地铁衔接"
        estimate_with_note = (duration_min, route_distance_km, mode_note)
        route_cache[cache_key] = estimate_with_note
        return estimate_with_note

    def _route_cache(self) -> dict[tuple[str, str, str, str], tuple[int, float, str]]:
        cache = getattr(self, "_route_estimate_cache", None)
        if cache is None:
            cache = {}
            setattr(self, "_route_estimate_cache", cache)
        return cache

    @staticmethod
    def _coord(location: Any) -> str:
        return f"{location.longitude},{location.latitude}"

    def _parse_route_result(
        self,
        payload: Any,
        *,
        fallback_distance_km: float,
    ) -> tuple[int, float] | None:
        if not isinstance(payload, dict):
            return None
        route = payload.get("route")
        if not isinstance(route, dict):
            return None

        candidates = route.get("paths") or route.get("transits") or []
        if not isinstance(candidates, list) or not candidates:
            return None
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        duration = self._safe_float(first.get("duration"))
        distance = self._safe_float(first.get("distance"))
        if duration is None or duration <= 0:
            return None
        if distance is None or distance <= 0:
            distance = fallback_distance_km * 1000
        return max(5, round(duration / 60)), max(0.1, distance / 1000)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_time_minutes(value: str) -> int | None:
        try:
            hour, minute = value.split(":", 1)
            return int(hour) * 60 + int(minute)
        except (AttributeError, ValueError):
            return None

    def _normalize_schedule(self, schedule: list[ScheduleItem]) -> list[ScheduleItem]:
        """Sort timeline items and drop reversed or out-of-day slots."""

        cleaned: list[ScheduleItem] = []
        for item in sorted(schedule, key=lambda entry: self._parse_time_minutes(entry.time) or 0):
            start = self._parse_time_minutes(item.time)
            end = self._parse_time_minutes(item.end_time)
            if start is None or end is None:
                continue
            if start >= 20 * 60 or end <= start:
                continue
            if end > 20 * 60:
                item = item.model_copy(update={"end_time": "20:00"})
            cleaned.append(item)
        return cleaned

    def _fill_schedule_gaps(self, schedule: list[ScheduleItem]) -> list[ScheduleItem]:
        """Insert practical rest/free-exploration blocks for long idle gaps."""

        schedule = self._normalize_schedule(schedule)
        if len(schedule) < 2:
            return schedule

        ordered = schedule
        filled: list[ScheduleItem] = []
        for index, item in enumerate(ordered):
            filled.append(item)
            if index >= len(ordered) - 1:
                continue

            end = self._parse_time_minutes(item.end_time)
            next_start = self._parse_time_minutes(ordered[index + 1].time)
            if end is None or next_start is None:
                continue

            gap = next_start - end
            if gap < 20:
                continue

            item_type = "rest" if gap < 120 else "free"
            activity = "周边慢游与短暂休整" if gap < 120 else "周边街区慢游 / 返回酒店整备"
            notes = (
                "避免两个正式项目之间空等，可在上一站附近补充休息、拍照或短距离闲逛。"
                if gap < 120
                else "该空档较长，建议安排返回酒店整理、午休，或选择上一站附近的轻量街区活动。"
            )
            filled.append(
                ScheduleItem(
                    time=item.end_time,
                    end_time=ordered[index + 1].time,
                    activity=activity,
                    location=item.location,
                    notes=notes,
                    item_type=item_type,
                )
            )
        return self._normalize_schedule(filled)

    # ── Budget ────────────────────────────────────────────────────────────

    def _repair_and_validate_days(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
    ) -> tuple[list[DayPlan], list[str]]:
        """Final deterministic quality gate before returning the itinerary."""

        repaired_days: list[DayPlan] = []
        notes: list[str] = []
        for day in days:
            timeline, day_notes = self._repair_timeline(day.timeline)
            if day_notes:
                notes.append(f"第 {day.day_index + 1} 天已修正时间轴问题")

            if len(day.attractions) > 3 and request.transportation == "public transit + walking":
                notes.append(f"第 {day.day_index + 1} 天公共交通景点偏多，建议现场保留弹性")

            meal_types = {meal.type for meal in day.meals}
            if "lunch" not in meal_types:
                notes.append(f"第 {day.day_index + 1} 天缺少明确午餐安排")
            if "dinner" not in meal_types:
                notes.append(f"第 {day.day_index + 1} 天缺少明确晚餐安排")

            max_leg = self._max_day_leg_km(day.attractions)
            if max_leg > 18 and request.transportation == "public transit + walking":
                notes.append(f"第 {day.day_index + 1} 天存在 {max_leg:.0f} 公里以上跨区移动")

            repaired_days.append(day.model_copy(update={"timeline": timeline}))

        return repaired_days, list(dict.fromkeys(notes))

    def _repair_timeline(
        self,
        timeline: list[ScheduleItem],
    ) -> tuple[list[ScheduleItem], list[str]]:
        normalized = self._normalize_schedule(timeline)
        if not normalized:
            return [], ["empty timeline"]

        repaired: list[ScheduleItem] = []
        notes: list[str] = []
        cursor = 8 * 60 + 30
        for item in normalized:
            start = self._parse_time_minutes(item.time)
            end = self._parse_time_minutes(item.end_time)
            if start is None or end is None:
                notes.append("invalid time")
                continue

            duration = end - start
            if start < cursor:
                if item.item_type in {"transit", "rest", "free"} and end <= cursor + 5:
                    notes.append("dropped overlap")
                    continue
                start = cursor
                end = min(start + duration, 20 * 60)
                if end <= start:
                    notes.append("dropped overlap")
                    continue
                item = item.model_copy(
                    update={
                        "time": self._fmt_time(start),
                        "end_time": self._fmt_time(end),
                    }
                )
                notes.append("shifted overlap")

            repaired.append(item)
            cursor = self._parse_time_minutes(item.end_time) or end

        return self._fill_schedule_gaps(repaired), notes

    def _max_day_leg_km(self, attractions: list[Attraction]) -> float:
        if len(attractions) < 2:
            return 0.0
        max_leg = 0.0
        for first, second in zip(attractions, attractions[1:]):
            max_leg = max(
                max_leg,
                self._geo_distance_km(
                    first.location.longitude,
                    first.location.latitude,
                    second.location.longitude,
                    second.location.latitude,
                ),
            )
        return max_leg

    def _calculate_budget(
        self, request: TravelPlanRequest, days: list[DayPlan]
    ) -> Budget:
        details: list[BudgetDetail] = []

        for day in days:
            for att in day.attractions:
                subtotal = att.ticket_price * request.travelers
                if subtotal > 0:
                    details.append(BudgetDetail(
                        category="attractions",
                        item=f"{day.date} {att.name}",
                        unit_cost=att.ticket_price,
                        quantity=request.travelers,
                        subtotal=subtotal,
                        note="每人门票估算。",
                    ))

        hotel = next((d.hotel for d in days if d.hotel), None)
        hotel_nights = max(request.days_count - 1, 0)
        if hotel and hotel_nights > 0:
            details.append(BudgetDetail(
                category="hotels",
                item=hotel.name,
                unit_cost=hotel.estimated_cost,
                quantity=hotel_nights,
                subtotal=hotel.estimated_cost * hotel_nights,
                note=f"{hotel_nights}晚住宿（单间）。",
            ))

        for day in days:
            for meal in day.meals:
                subtotal = meal.estimated_cost * request.travelers
                details.append(BudgetDetail(
                    category="meals",
                    item=f"{day.date} {meal.type}：{meal.name}",
                    unit_cost=meal.estimated_cost,
                    quantity=request.travelers,
                    subtotal=subtotal,
                    note="每人餐费估算。",
                ))

        transport_unit = self._transport_unit_cost(request)
        for day in days:
            subtotal = transport_unit * request.travelers
            details.append(BudgetDetail(
                category="transportation",
                item=f"{day.date} {request.transportation}",
                unit_cost=transport_unit,
                quantity=request.travelers,
                subtotal=subtotal,
                note="每人每天本地交通估算。",
            ))

        total_attractions = sum(d.subtotal for d in details if d.category == "attractions")
        total_hotels = sum(d.subtotal for d in details if d.category == "hotels")
        total_meals = sum(d.subtotal for d in details if d.category == "meals")
        total_transportation = sum(
            d.subtotal for d in details if d.category == "transportation"
        )

        return Budget(
            total_attractions=total_attractions,
            total_hotels=total_hotels,
            total_meals=total_meals,
            total_transportation=total_transportation,
            total=total_attractions + total_hotels + total_meals + total_transportation,
            hotel_nights=hotel_nights,
            travelers=request.travelers,
            details=details,
        )

    @staticmethod
    def _transport_unit_cost(request: TravelPlanRequest) -> int:
        if "自驾" in request.transportation or "self-driving" in request.transportation:
            return 150
        if "出租" in request.transportation or "taxi" in request.transportation:
            return 100
        return 50

    @staticmethod
    def _check_budget(request: TravelPlanRequest, budget: Budget) -> str:
        if not request.budget:
            return ""
        ratio = budget.total / max(request.budget, 1)
        if ratio > 1.3:
            return (
                f"⚠️ 预计总费用 {budget.total} 元较您的预算 {request.budget} 元"
                f"超出 {int((ratio - 1) * 100)}%，建议精简行程或选择更经济的住宿。"
            )
        if ratio > 1.05:
            return (
                f"当前方案预计费用 {budget.total} 元，略高于预算 {request.budget} 元，可酌情调整。"
            )
        return f"当前方案预计费用 {budget.total} 元，在预算 {request.budget} 元范围内。"

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
