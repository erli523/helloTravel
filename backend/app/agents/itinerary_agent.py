"""PlannerAgent implementation."""

from datetime import timedelta

from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.agents.prompts import PLANNER_AGENT_PROMPT
from app.models.travel import (
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    Meal,
    TravelPlanRequest,
    TripPlan,
    WeatherInfo,
)


class PlannerAgent(BaseAgent):
    """Integrates specialist Agent outputs into a complete trip plan."""

    name = "PlannerAgent"
    prompt_template = PLANNER_AGENT_PROMPT

    async def run(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        weather_info: list[WeatherInfo],
        hotels: list[Hotel],
        planner_query: str,
    ) -> AgentResult[TripPlan]:
        days = self._build_days(request, attractions, hotels)
        budget = self._calculate_budget(request, days)
        plan = TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=weather_info,
            overall_suggestions=(
                "Keep 1-2 flexible hours each day. If weather worsens, replace "
                "outdoor attractions with museums or indoor neighborhoods."
            ),
            budget=budget,
        )

        return AgentResult(
            data=plan,
            trace=AgentTrace(
                agent_name=self.name,
                prompt=self.prompt_template,
                user_query=planner_query,
                tool_calls=[],
                summary=(
                    f"Generated {len(days)} daily plans with budget {budget.total} CNY."
                ),
            ),
        )

    def _build_days(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        hotels: list[Hotel],
    ) -> list[DayPlan]:
        selected_hotel = hotels[0] if hotels else None
        plans: list[DayPlan] = []
        attractions_per_day = 3 if len(attractions) >= request.days_count * 3 else 2

        for index in range(request.days_count):
            start = index * attractions_per_day
            day_attractions = attractions[start : start + attractions_per_day]
            if not day_attractions:
                day_attractions = attractions[index::request.days_count] or attractions[:1]

            plans.append(
                DayPlan(
                    date=request.start_date + timedelta(days=index),
                    day_index=index,
                    description=(
                        f"Day {index + 1} focuses on {request.city} experiences "
                        "with a balanced pace."
                    ),
                    transportation=request.transportation,
                    accommodation=(
                        selected_hotel.name if selected_hotel else request.accommodation
                    ),
                    hotel=selected_hotel,
                    attractions=day_attractions,
                    meals=[
                        Meal(
                            type="breakfast",
                            name="Hotel breakfast",
                            description="Convenient start before the first attraction.",
                            estimated_cost=40,
                        ),
                        Meal(
                            type="lunch",
                            name=f"{request.city} local lunch",
                            description="Choose a restaurant near the planned route.",
                            estimated_cost=80,
                        ),
                        Meal(
                            type="dinner",
                            name=f"{request.city} signature dinner",
                            description="Arrange near a transit-friendly area.",
                            estimated_cost=120,
                        ),
                    ],
                )
            )

        return plans

    def _calculate_budget(self, request: TravelPlanRequest, days: list[DayPlan]) -> Budget:
        total_attractions = sum(
            attraction.ticket_price
            for day in days
            for attraction in day.attractions
        ) * request.travelers
        total_hotels = sum(day.hotel.estimated_cost for day in days if day.hotel)
        total_meals = sum(
            meal.estimated_cost for day in days for meal in day.meals
        ) * request.travelers
        total_transportation = 80 * len(days) * request.travelers

        return Budget(
            total_attractions=total_attractions,
            total_hotels=total_hotels,
            total_meals=total_meals,
            total_transportation=total_transportation,
            total=total_attractions
            + total_hotels
            + total_meals
            + total_transportation,
        )


# Backward-compatible alias for older service imports.
ItineraryAgent = PlannerAgent
