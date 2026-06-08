"""Meal allocation helpers for itinerary days."""

from __future__ import annotations

from app.models.travel import Attraction, Meal, TravelPlanRequest


class MealAllocator:
    """Assign lunch and dinner candidates to days without cross-day repetition."""

    def __init__(self) -> None:
        self.used_names: set[str] = set()

    def reset(self) -> None:
        self.used_names.clear()

    def build_geo_meals(
        self,
        request: TravelPlanRequest,
        meals: list[Meal],
        day_attractions: list[Attraction],
    ) -> list[Meal]:
        if day_attractions:
            longitude = sum(item.location.longitude for item in day_attractions) / len(day_attractions)
            latitude = sum(item.location.latitude for item in day_attractions) / len(day_attractions)

            def distance(meal: Meal) -> float:
                if meal.location is None:
                    return 999.0
                return (
                    (meal.location.longitude - longitude) ** 2
                    + (meal.location.latitude - latitude) ** 2
                ) ** 0.5
        else:

            def distance(_: Meal) -> float:
                return 0.0

        lunches = sorted(
            [meal for meal in meals if meal.type in ("lunch", "snack")],
            key=distance,
        )
        dinners = sorted(
            [meal for meal in meals if meal.type == "dinner"],
            key=distance,
        )
        lunch = self.pick_unused_meal(lunches)
        if lunch:
            self.used_names.add(lunch.name)
        dinner = self.pick_unused_meal(dinners)
        if dinner:
            self.used_names.add(dinner.name)
        return self.assemble_meals(request, lunch, dinner)

    def pick_unused_meal(self, meals: list[Meal]) -> Meal | None:
        for meal in meals:
            if meal.name not in self.used_names:
                return meal
        return meals[0] if meals else None

    @staticmethod
    def assemble_meals(
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
                    description="就近选择当地特色餐厅。",
                    estimated_cost=70,
                )
            ),
            (
                dinner.model_copy(update={"type": "dinner"})
                if dinner
                else Meal(
                    type="dinner",
                    name=f"{request.city}招牌晚餐",
                    description="安排当地代表性晚餐。",
                    estimated_cost=100,
                )
            ),
        ]
