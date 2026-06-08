"""Budget calculation service for generated travel plans."""

from __future__ import annotations

from app.models.travel import Budget, BudgetDetail, DayPlan, TravelPlanRequest


class BudgetService:
    """Calculate trip budget details independently from itinerary planning."""

    def calculate(self, request: TravelPlanRequest, days: list[DayPlan]) -> Budget:
        details: list[BudgetDetail] = []

        for day in days:
            for attraction in day.attractions:
                subtotal = attraction.ticket_price * request.travelers
                if subtotal > 0:
                    details.append(
                        BudgetDetail(
                            category="attractions",
                            item=f"{day.date} {attraction.name}",
                            unit_cost=attraction.ticket_price,
                            quantity=request.travelers,
                            subtotal=subtotal,
                            note="Estimated per-person ticket cost.",
                        )
                    )

        hotel = next((day.hotel for day in days if day.hotel), None)
        hotel_nights = max(request.days_count - 1, 0)
        if hotel and hotel_nights > 0:
            details.append(
                BudgetDetail(
                    category="hotels",
                    item=hotel.name,
                    unit_cost=hotel.estimated_cost,
                    quantity=hotel_nights,
                    subtotal=hotel.estimated_cost * hotel_nights,
                    note=f"{hotel_nights} hotel night(s), room estimate.",
                )
            )

        for day in days:
            for meal in day.meals:
                subtotal = meal.estimated_cost * request.travelers
                details.append(
                    BudgetDetail(
                        category="meals",
                        item=f"{day.date} {meal.type}: {meal.name}",
                        unit_cost=meal.estimated_cost,
                        quantity=request.travelers,
                        subtotal=subtotal,
                        note="Estimated per-person meal cost.",
                    )
                )

        transport_unit = self.transport_unit_cost(request)
        for day in days:
            subtotal = transport_unit * request.travelers
            details.append(
                BudgetDetail(
                    category="transportation",
                    item=f"{day.date} {request.transportation}",
                    unit_cost=transport_unit,
                    quantity=request.travelers,
                    subtotal=subtotal,
                    note="Estimated local transportation cost per person per day.",
                )
            )

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
    def transport_unit_cost(request: TravelPlanRequest) -> int:
        transportation = request.transportation.lower()
        if "自驾" in request.transportation or "self-driving" in transportation:
            return 150
        if "出租" in request.transportation or "taxi" in transportation:
            return 100
        return 50

    @staticmethod
    def check_constraint(request: TravelPlanRequest, budget: Budget) -> str:
        if not request.budget:
            return ""
        ratio = budget.total / max(request.budget, 1)
        if ratio > 1.3:
            return (
                f"预计总费用 {budget.total} 元较您的预算 {request.budget} 元"
                f"超出 {int((ratio - 1) * 100)}%，建议精简行程或选择更经济的住宿。"
            )
        if ratio > 1.05:
            return (
                f"当前方案预计费用 {budget.total} 元，略高于预算 "
                f"{request.budget} 元，可酌情调整。"
            )
        return f"当前方案预计费用 {budget.total} 元，在预算 {request.budget} 元范围内。"
