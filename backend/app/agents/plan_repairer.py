"""Plan mutation helpers used by the PlannerAgent ReAct loop."""

from __future__ import annotations

from app.agents.geo_day_planner import GeoDayPlanner
from app.agents.plan_quality_observer import PlanQualityObserver
from app.agents.schedule_builder import ScheduleBuilder
from app.models.travel import Attraction, DayPlan, Location, Meal, TravelPlanRequest


class PlanRepairer:
    """Execute deterministic itinerary repair actions."""

    def __init__(
        self,
        geo_day_planner: GeoDayPlanner | None = None,
        schedule_builder: ScheduleBuilder | None = None,
        quality_observer: PlanQualityObserver | None = None,
    ) -> None:
        self.geo_day_planner = geo_day_planner or GeoDayPlanner()
        self.schedule_builder = schedule_builder or ScheduleBuilder()
        self.quality_observer = quality_observer or PlanQualityObserver()

    def rebalance_overloaded_days(
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
            receiver_index = self.find_lighter_day_index(mutable_days, exclude=index)
            if receiver_index is None:
                continue
            moved = day.attractions[-1]
            source_attractions = day.attractions[:-1]
            receiver = mutable_days[receiver_index]
            receiver_attractions = receiver.attractions + [moved]

            mutable_days[index] = day.model_copy(
                update={
                    "attractions": source_attractions,
                    "timeline": self._timeline(request, source_attractions, day.meals),
                }
            )
            mutable_days[receiver_index] = receiver.model_copy(
                update={
                    "attractions": receiver_attractions,
                    "timeline": self._timeline(request, receiver_attractions, receiver.meals),
                }
            )
            notes.append(
                f"Moved {moved.name} from day {day.day_index + 1} to day "
                f"{receiver.day_index + 1} to reduce public-transit load"
            )

        return mutable_days, notes

    @staticmethod
    def find_lighter_day_index(days: list[DayPlan], *, exclude: int) -> int | None:
        candidates = [
            (index, len(day.attractions))
            for index, day in enumerate(days)
            if index != exclude and len(day.attractions) < 3
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[1])[0]

    def fill_sparse_days(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
        candidate_attractions: list[Attraction] | None = None,
    ) -> tuple[list[DayPlan], list[str]]:
        candidate_attractions = candidate_attractions or []
        notes: list[str] = []
        mutable_days = list(days)
        for index, day in enumerate(list(mutable_days)):
            if len(day.attractions) >= 3:
                continue

            current_day = day
            added: list[Attraction] = []
            while len(current_day.attractions) < 3:
                used_attractions = [
                    attraction
                    for current in mutable_days
                    for attraction in current.attractions
                ] + added
                candidate = self.find_unused_candidate_for_day(
                    current_day,
                    used_attractions,
                    candidate_attractions,
                )
                if candidate is None:
                    candidate = self.build_local_experience_candidate(
                        request,
                        current_day,
                        len(added),
                    )
                if candidate is None:
                    break
                if any(
                    self.quality_observer.same_attraction_complex(candidate, attraction)
                    for attraction in current_day.attractions
                ):
                    break

                added.append(candidate)
                current_day = current_day.model_copy(
                    update={"attractions": current_day.attractions + [candidate]}
                )

            if added:
                new_day_attractions = self.geo_day_planner.order_route(
                    current_day.attractions,
                    current_day.hotel,
                )
                mutable_days[index] = day.model_copy(
                    update={
                        "attractions": new_day_attractions,
                        "timeline": self._timeline(request, new_day_attractions, day.meals),
                    }
                )
                notes.append(
                    f"Added {len(added)} activity candidate(s) to day {day.day_index + 1} "
                    f"to reduce idle time: {', '.join(item.name for item in added)}"
                )
                continue

            donor_index = max(
                range(len(mutable_days)),
                key=lambda item: len(mutable_days[item].attractions),
                default=index,
            )
            if donor_index == index or len(mutable_days[donor_index].attractions) <= 3:
                continue
            donor = mutable_days[donor_index]
            moved = donor.attractions[-1]
            if any(
                self.quality_observer.same_attraction_complex(moved, attraction)
                for attraction in day.attractions
            ):
                continue
            new_day_attractions = self.geo_day_planner.order_route(
                day.attractions + [moved],
                day.hotel,
            )
            new_donor_attractions = donor.attractions[:-1]
            mutable_days[index] = day.model_copy(
                update={
                    "attractions": new_day_attractions,
                    "timeline": self._timeline(request, new_day_attractions, day.meals),
                }
            )
            mutable_days[donor_index] = donor.model_copy(
                update={
                    "attractions": new_donor_attractions,
                    "timeline": self._timeline(request, new_donor_attractions, donor.meals),
                }
            )
            notes.append(f"Added {moved.name} to day {day.day_index + 1} to reduce idle time")
        return mutable_days, notes

    def dedupe_duplicate_attractions(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
        candidate_attractions: list[Attraction],
    ) -> tuple[list[DayPlan], list[str]]:
        notes: list[str] = []
        mutable_days = list(days)
        accepted: list[Attraction] = []

        for day_index, day in enumerate(list(mutable_days)):
            new_attractions: list[Attraction] = []
            changed = False
            for attraction in day.attractions:
                duplicate = next(
                    (
                        seen
                        for seen in accepted
                        if self.quality_observer.same_attraction_complex(attraction, seen)
                    ),
                    None,
                )
                if duplicate is None:
                    new_attractions.append(attraction)
                    accepted.append(attraction)
                    continue

                replacement = self.find_unused_candidate_for_day(
                    day,
                    accepted + new_attractions,
                    candidate_attractions,
                )
                if replacement is not None:
                    new_attractions.append(replacement)
                    accepted.append(replacement)
                    notes.append(
                        f"Replaced duplicate {attraction.name} on day {day.day_index + 1} "
                        f"with {replacement.name}"
                    )
                elif len(day.attractions) > 1:
                    notes.append(
                        f"Removed duplicate {attraction.name} from day {day.day_index + 1}"
                    )
                else:
                    new_attractions.append(attraction)
                    accepted.append(attraction)
                changed = True

            if changed:
                ordered = self.geo_day_planner.order_route(new_attractions, day.hotel)
                mutable_days[day_index] = day.model_copy(
                    update={
                        "attractions": ordered,
                        "timeline": self._timeline(request, ordered, day.meals),
                    }
                )

        return mutable_days, notes

    def dedupe_duplicate_meals(
        self,
        request: TravelPlanRequest,
        days: list[DayPlan],
        candidate_meals: list[Meal],
    ) -> tuple[list[DayPlan], list[str]]:
        notes: list[str] = []
        mutable_days = list(days)
        used: dict[tuple[str, str], int] = {}

        for day_index, day in enumerate(list(mutable_days)):
            new_meals: list[Meal] = []
            changed = False
            for meal in day.meals:
                if meal.type == "breakfast":
                    new_meals.append(meal)
                    continue

                key = (meal.type, meal.name)
                if key not in used:
                    used[key] = day.day_index
                    new_meals.append(meal)
                    continue

                replacement = self.find_unused_meal_candidate(
                    meal,
                    candidate_meals,
                    {name for meal_type, name in used if meal_type == meal.type},
                )
                if replacement is None:
                    new_meals.append(meal)
                    continue

                used[(replacement.type, replacement.name)] = day.day_index
                new_meals.append(replacement)
                changed = True
                notes.append(
                    f"Replaced duplicate {meal.type} {meal.name} on day "
                    f"{day.day_index + 1} with {replacement.name}"
                )

            if changed:
                mutable_days[day_index] = day.model_copy(
                    update={
                        "meals": new_meals,
                        "timeline": self._timeline(request, day.attractions, new_meals),
                    }
                )

        return mutable_days, notes

    @staticmethod
    def find_unused_meal_candidate(
        duplicate_meal: Meal,
        candidate_meals: list[Meal],
        used_names: set[str],
    ) -> Meal | None:
        for candidate in candidate_meals:
            if candidate.type == duplicate_meal.type and candidate.name not in used_names:
                return candidate
        return None

    def build_local_experience_candidate(
        self,
        request: TravelPlanRequest,
        day: DayPlan,
        offset_index: int,
    ) -> Attraction | None:
        anchor = day.attractions[-1] if day.attractions else None
        if anchor is None:
            return None

        activity_templates = [
            ("周边街区与茶馆体验", 90),
            ("附近市集与小吃街漫游", 75),
        ]
        label, duration = activity_templates[offset_index % len(activity_templates)]
        delta = 0.004 * (offset_index + 1)
        return Attraction(
            name=f"{anchor.name}{label}",
            address=anchor.address or request.city,
            location=Location(
                longitude=max(min(anchor.location.longitude + delta, 180), -180),
                latitude=max(min(anchor.location.latitude + delta, 90), -90),
            ),
            visit_duration=duration,
            description=(
                f"基于{anchor.name}附近安排的就近体验活动，用于衔接下午时段；"
                "建议现场结合茶馆、书店、街巷、市集或小吃店灵活选择。"
            ),
            category="就近体验",
            rating=None,
            image_url=None,
            ticket_price=0,
        )

    def find_unused_candidate_for_day(
        self,
        day: DayPlan,
        used_attractions: list[Attraction],
        candidate_attractions: list[Attraction],
    ) -> Attraction | None:
        usable = [
            candidate
            for candidate in candidate_attractions
            if not any(
                self.quality_observer.same_attraction_complex(candidate, used)
                for used in used_attractions
            )
            and not any(
                self.quality_observer.same_attraction_complex(candidate, current)
                for current in day.attractions
            )
        ]
        if not usable:
            return None

        if any(ScheduleBuilder.is_evening_attraction(attraction) for attraction in day.attractions):
            daytime_usable = [
                candidate
                for candidate in usable
                if not ScheduleBuilder.is_evening_attraction(candidate)
            ]
            if daytime_usable:
                usable = daytime_usable

        if not day.attractions:
            return usable[0]

        center_lng = sum(attraction.location.longitude for attraction in day.attractions) / len(
            day.attractions
        )
        center_lat = sum(attraction.location.latitude for attraction in day.attractions) / len(
            day.attractions
        )
        return min(
            usable,
            key=lambda candidate: (
                (candidate.location.longitude - center_lng) ** 2
                + (candidate.location.latitude - center_lat) ** 2
            ),
        )

    def _timeline(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        meals: list[Meal],
    ):
        return self.schedule_builder.fill_schedule_gaps(
            self.schedule_builder.build_default_schedule(request, attractions, meals)
        )
