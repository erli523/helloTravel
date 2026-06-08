"""Route enrichment helper for itinerary timelines."""

from __future__ import annotations

from typing import Any

from app.agents.schedule_builder import ScheduleBuilder
from app.models.travel import Attraction, DayPlan, ScheduleItem, TravelPlanRequest
from app.utils.geo import geo_distance_km


class RouteEnricher:
    """Use Amap route tools to enrich adjacent itinerary transit blocks."""

    def __init__(
        self,
        amap_tools: Any | None = None,
        context_bus: Any | None = None,
        agent_name: str = "PlannerAgent",
    ) -> None:
        self.amap_tools = amap_tools
        self.context_bus = context_bus
        self.agent_name = agent_name
        self.cache: dict[tuple[str, str, str, str], tuple[int, float, str]] = {}

    async def enrich_route_transits(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
    ) -> list[DayPlan]:
        if self.amap_tools is None:
            return days

        enriched_days: list[DayPlan] = []
        for day in days:
            timeline = await self.enrich_day_transits(request, day)
            enriched_days.append(day.model_copy(update={"timeline": timeline}))
        return enriched_days

    async def enrich_day_transits(
        self,
        request: TravelPlanRequest,
        day: DayPlan,
    ) -> list[ScheduleItem]:
        if not day.timeline or len(day.attractions) < 2:
            return day.timeline

        by_name = {attraction.name: attraction for attraction in day.attractions}
        updated: list[ScheduleItem] = []
        for index, item in enumerate(day.timeline):
            if item.item_type != "transit":
                updated.append(item)
                continue

            previous_attraction = self.nearest_timeline_attraction(
                day.timeline,
                by_name,
                start=index - 1,
                step=-1,
            )
            next_attraction = self.nearest_timeline_attraction(
                day.timeline,
                by_name,
                start=index + 1,
                step=1,
            )
            if previous_attraction is None or next_attraction is None:
                updated.append(item)
                continue

            estimate = await self.route_estimate(
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
                    self.agent_name,
                    "Queried route estimate for adjacent itinerary stops.",
                    origin=previous_attraction.name,
                    destination=next_attraction.name,
                    duration_min=duration_min,
                    distance_km=round(distance_km, 2),
                )

            start = ScheduleBuilder.parse_time_minutes(item.time)
            next_start = ScheduleBuilder.parse_time_minutes(
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
                        "end_time": ScheduleBuilder.fmt_time(end),
                        "activity": f"前往{next_attraction.name}",
                        "location": f"{previous_attraction.name} -> {next_attraction.name}",
                        "notes": (
                            f"{mode_note}，高德路线估算约 {duration_min} 分钟，"
                            f"距离约 {distance_km:.1f} 公里。"
                        ),
                    }
                )
            )

        return ScheduleBuilder.fill_schedule_gaps(updated)

    @staticmethod
    def nearest_timeline_attraction(
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
                attraction = RouteEnricher.match_timeline_attraction(item, attractions_by_name)
                if attraction is not None:
                    return attraction
            index += step
        return None

    @staticmethod
    def match_timeline_attraction(
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

    async def route_estimate(
        self,
        request: TravelPlanRequest,
        origin: Attraction,
        destination: Attraction,
    ) -> tuple[int, float, str] | None:
        if self.amap_tools is None:
            return None

        distance_km = geo_distance_km(
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
            self.coord(origin.location),
            self.coord(destination.location),
            tool_name,
            request.city,
        )
        if cache_key in self.cache:
            return self.cache[cache_key]

        result = await self.amap_tools.call_tool(
            tool_name,
            {
                "origin": self.coord(origin.location),
                "destination": self.coord(destination.location),
                "city": request.city,
            },
        )
        estimate = self.parse_route_result(result.get("result"), fallback_distance_km=distance_km)
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
        self.cache[cache_key] = estimate_with_note
        return estimate_with_note

    @staticmethod
    def coord(location: Any) -> str:
        return f"{location.longitude},{location.latitude}"

    def parse_route_result(
        self,
        result: Any,
        *,
        fallback_distance_km: float,
    ) -> tuple[int, float] | None:
        if not isinstance(result, dict):
            return None
        route = result.get("route") if isinstance(result.get("route"), dict) else result
        paths = route.get("paths") if isinstance(route, dict) else None
        transits = route.get("transits") if isinstance(route, dict) else None
        candidate = None
        if isinstance(paths, list) and paths:
            candidate = paths[0]
        elif isinstance(transits, list) and transits:
            candidate = transits[0]
        elif isinstance(route, dict):
            candidate = route
        if not isinstance(candidate, dict):
            return None

        duration = self.safe_float(candidate.get("duration") or route.get("duration"))
        distance = self.safe_float(candidate.get("distance") or route.get("distance"))
        if duration is None or duration <= 0:
            return None
        if distance is None or distance <= 0:
            distance = fallback_distance_km * 1000
        return max(5, round(duration / 60)), max(0.1, distance / 1000)

    @staticmethod
    def safe_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
