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

        # 3. Budget + constraint check
        budget = self._calculate_budget(request, days)
        budget_note = self._check_budget(request, budget)
        if budget_note:
            overall_suggestions += f"\n{budget_note}"

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

        context = self._format_planning_context(request, attractions, weather_info, hotels, meals)
        timeout = getattr(getattr(llm, "settings", None), "llm_timeout", 60.0)
        try:
            return await asyncio.wait_for(
                llm.generate_itinerary(
                    system_prompt=PLANNER_ITINERARY_PROMPT,
                    planning_context=context,
                ),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Exception):
            return None

    def _format_planning_context(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        weather_info: list[WeatherInfo],
        hotels: list[Hotel],
        meals: list[Meal],
    ) -> str:
        lines: list[str] = []

        # User requirements
        preferences = "、".join(request.preferences) or "通用旅游"
        budget_note = f"（总预算上限：{request.budget}元）" if request.budget else ""
        lines += [
            "【用户需求】",
            f"目的地：{request.city}，日期：{request.start_date} 至 {request.end_date}，"
            f"共{request.days_count}天",
            f"人数：{request.travelers}人，预算档次：{request.budget_level}{budget_note}",
            f"偏好：{preferences}，交通：{request.transportation}，住宿：{request.accommodation}",
            "",
        ]

        # Attractions (with coordinates for proximity reasoning)
        lines.append(f"【候选景点】（共{len(attractions)}个，请使用原始名称）")
        for i, att in enumerate(attractions, 1):
            rating_str = f"{att.rating}" if att.rating is not None else "暂无"
            lines.append(
                f"{i}. {att.name} | {att.address} "
                f"| 坐标({att.location.longitude:.4f},{att.location.latitude:.4f}) "
                f"| 评分:{rating_str} | 门票:{att.ticket_price}元 "
                f"| 建议游览:{att.visit_duration}分钟 | 类别:{att.category}"
            )
        lines.append("")

        # Weather forecast
        lines.append("【天气预报】")
        for i, w in enumerate(weather_info, 1):
            lines.append(
                f"第{i}天 {w.date}：{w.day_weather}，"
                f"{w.day_temp}℃/{w.night_temp}℃，{w.wind_direction}风{w.wind_power}级"
            )
        lines.append("")

        # Hotels
        lines.append(f"【候选酒店】（共{len(hotels)}个，请选最合适的1家）")
        for i, h in enumerate(hotels, 1):
            lines.append(
                f"{i}. {h.name} | {h.address} | {h.price_range} | 评分:{h.rating}"
            )
        lines.append("")

        # Meals
        lines.append(f"【候选餐厅】（共{len(meals)}个，每天午餐和晚餐各选1家）")
        for i, m in enumerate(meals, 1):
            addr = m.address or "地址未知"
            lines.append(f"{i}. {m.name} | {addr} | 人均:{m.estimated_cost}元")

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

    @staticmethod
    def _parse_time_minutes(value: str) -> int | None:
        try:
            hour, minute = value.split(":", 1)
            return int(hour) * 60 + int(minute)
        except (AttributeError, ValueError):
            return None

    def _fill_schedule_gaps(self, schedule: list[ScheduleItem]) -> list[ScheduleItem]:
        """Insert practical rest/free-exploration blocks for long idle gaps."""

        if len(schedule) < 2:
            return schedule

        ordered = sorted(
            schedule,
            key=lambda item: self._parse_time_minutes(item.time) or 0,
        )
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
            if gap < 90:
                continue

            item_type = "rest" if gap < 180 else "free"
            activity = "周边慢游与咖啡休息" if gap < 180 else "周边街区慢游 / 返回酒店整备"
            notes = (
                "避免两个正式项目之间空等，可在上一站附近补充休息、拍照或短距离闲逛。"
                if gap < 180
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
        return filled

    # ── Budget ────────────────────────────────────────────────────────────

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
