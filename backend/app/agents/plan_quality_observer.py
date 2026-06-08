"""Quality observation helpers for the PlannerAgent ReAct loop."""

from __future__ import annotations

from typing import Any, Callable

from app.agents.route_enricher import RouteEnricher
from app.agents.schedule_builder import ScheduleBuilder
from app.models.travel import Attraction, DayPlan, Meal, ScheduleItem, TravelPlanRequest
from app.utils.geo import geo_distance_km


class PlanQualityObserver:
    """Detect actionable itinerary quality issues without mutating the plan."""

    def observe(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
        *,
        has_route_tools: bool,
        max_day_leg_km: Callable[[list[Attraction]], float],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for day in days:
            timeline = ScheduleBuilder.normalize_schedule(day.timeline)
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
                first_end = ScheduleBuilder.parse_time_minutes(first.end_time)
                second_start = ScheduleBuilder.parse_time_minutes(second.time)
                if first_end is None or second_start is None:
                    continue
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
                            "action": "fill_sparse_days",
                        }
                    )

            if len(day.attractions) < 3 and request.days_count > 1:
                issues.append(
                    {
                        "code": "sparse_day",
                        "severity": "medium",
                        "day_index": day.day_index,
                        "count": len(day.attractions),
                        "action": "fill_sparse_days",
                    }
                )

            for item in timeline:
                item_start = ScheduleBuilder.parse_time_minutes(item.time)
                item_end = ScheduleBuilder.parse_time_minutes(item.end_time)
                if (
                    item.item_type in {"free", "rest"}
                    and item_start is not None
                    and item_end is not None
                    and item_end - item_start >= 120
                ):
                    issues.append(
                        {
                            "code": "long_placeholder_block",
                            "severity": "medium",
                            "day_index": day.day_index,
                            "minutes": item_end - item_start,
                            "action": "fill_sparse_days",
                        }
                    )

                if item.item_type == "attraction" and self.schedule_item_looks_evening(item):
                    start = ScheduleBuilder.parse_time_minutes(item.time)
                    if start is not None and start < 18 * 60:
                        issues.append(
                            {
                                "code": "evening_attraction_too_early",
                                "severity": "high",
                                "day_index": day.day_index,
                                "activity": item.activity,
                                "action": "repair_timeline",
                            }
                        )

            if has_route_tools and self.day_has_unestimated_transit(day):
                issues.append(
                    {
                        "code": "missing_route_estimate",
                        "severity": "medium",
                        "day_index": day.day_index,
                        "action": "enrich_routes",
                    }
                )

            if request.transportation == "public transit + walking" and len(day.attractions) > 3:
                issues.append(
                    {
                        "code": "overloaded_public_transit_day",
                        "severity": "medium",
                        "day_index": day.day_index,
                        "count": len(day.attractions),
                        "action": "rebalance_day_load",
                    }
                )

            max_leg = max_day_leg_km(day.attractions)
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

        issues.extend(self.cross_day_duplicate_issues(days))
        issues.extend(self.duplicate_meal_issues(days))
        return issues

    def day_has_unestimated_transit(self, day: DayPlan) -> bool:
        if len(day.attractions) < 2:
            return False
        by_name = {attraction.name: attraction for attraction in day.attractions}
        for index, item in enumerate(day.timeline):
            if item.item_type != "transit":
                continue
            if "高德" in item.notes or "Amap" in item.notes:
                continue
            previous_attraction = RouteEnricher.nearest_timeline_attraction(
                day.timeline,
                by_name,
                start=index - 1,
                step=-1,
            )
            next_attraction = RouteEnricher.nearest_timeline_attraction(
                day.timeline,
                by_name,
                start=index + 1,
                step=1,
            )
            if previous_attraction is not None and next_attraction is not None:
                return True
        return False

    def cross_day_duplicate_issues(self, days: list[DayPlan]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        seen: list[tuple[int, Attraction]] = []
        for day in days:
            day_seen: list[Attraction] = []
            for attraction in day.attractions:
                same_day_match = next(
                    (
                        seen_attraction
                        for seen_attraction in day_seen
                        if self.same_attraction_complex(attraction, seen_attraction)
                    ),
                    None,
                )
                if same_day_match is not None:
                    issues.append(
                        {
                            "code": "same_day_duplicate_attraction",
                            "severity": "high",
                            "day_index": day.day_index,
                            "name": attraction.name,
                            "duplicate_of": same_day_match.name,
                            "action": "dedupe_attractions",
                        }
                    )
                    continue

                match = next(
                    (
                        (seen_day, seen_attraction)
                        for seen_day, seen_attraction in seen
                        if self.same_attraction_complex(attraction, seen_attraction)
                    ),
                    None,
                )
                if match:
                    issues.append(
                        {
                            "code": "cross_day_duplicate_attraction",
                            "severity": "high",
                            "day_index": day.day_index,
                            "name": attraction.name,
                            "duplicate_of_day": match[0],
                            "action": "dedupe_attractions",
                        }
                    )
                else:
                    seen.append((day.day_index, attraction))
                    day_seen.append(attraction)
        return issues

    @staticmethod
    def duplicate_meal_issues(days: list[DayPlan]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        seen: dict[tuple[str, str], int] = {}
        for day in days:
            for meal in day.meals:
                if meal.type == "breakfast":
                    continue
                key = (meal.type, meal.name)
                if key in seen:
                    issues.append(
                        {
                            "code": "duplicate_meal",
                            "severity": "medium",
                            "day_index": day.day_index,
                            "meal": meal.name,
                            "duplicate_of_day": seen[key],
                            "action": "dedupe_meals",
                        }
                    )
                else:
                    seen[key] = day.day_index
        return issues

    @staticmethod
    def same_attraction_complex(first: Attraction, second: Attraction) -> bool:
        local_categories = {"就近体验", "灏辫繎浣撻獙"}
        if first.category in local_categories or second.category in local_categories:
            return False
        distance = geo_distance_km(
            first.location.longitude,
            first.location.latitude,
            second.location.longitude,
            second.location.latitude,
        )
        if distance <= 0.12:
            return True
        first_key = PlanQualityObserver.canonical_attraction_name(first.name)
        second_key = PlanQualityObserver.canonical_attraction_name(second.name)
        return bool(
            first_key
            and second_key
            and (first_key in second_key or second_key in first_key)
        )

    @staticmethod
    def canonical_attraction_name(name: str) -> str:
        result = name.strip()
        noise = (
            "夜景",
            "观景台",
            "民俗风貌区",
            "风貌区",
            "景区",
            "景点",
            "入口",
            "出口",
            "广场",
            "澶滄櫙",
            "瑙傛櫙鍙",
            "姘戜織椋庤矊鍖",
            "椋庤矊鍖",
            "鏅尯",
            "鏅偣",
            "鍏ュ彛",
            "鍑哄彛",
            "骞垮満",
        )
        for token in noise:
            result = result.replace(token, "")
        return result.strip()

    @staticmethod
    def schedule_item_looks_evening(item: ScheduleItem) -> bool:
        text = " ".join([item.activity, item.location, item.notes])
        return any(
            token in text
            for token in (
                "夜景",
                "夜间",
                "夜游",
                "灯光",
                "洪崖洞",
                "一棵树",
                "澶滄櫙",
                "澶滈棿",
                "澶滄父",
                "鐏厜",
                "娲礀娲",
                "涓€妫垫爲",
            )
        )

    @staticmethod
    def quality_notes_from_issues(issues: Any) -> list[str]:
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
            elif code == "cross_day_duplicate_attraction":
                notes.append(f"Day {day} repeats a semantically duplicate attraction.")
            elif code == "duplicate_meal":
                notes.append(f"Day {day} repeats a restaurant already used on another day.")
            elif code == "sparse_day":
                notes.append(f"Day {day} has too few attractions and may contain idle time.")
        return notes
