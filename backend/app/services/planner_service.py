"""Service boundary for travel planning."""

from app.agents.base_agent import AgentTrace
from app.agents.trip_planner_agent import TripPlannerAgent
from app.models.travel import TravelPlanRequest, TripPlan
from app.services.trip_image_service import TripImageService
from app.services.validators import validate_trip_plan


class PlannerService:
    """Coordinates API layer and the multi-agent planning workflow."""

    def __init__(self) -> None:
        self.trip_planner_agent = TripPlannerAgent()
        self.trip_image_service = TripImageService()

    async def create_plan(self, request: TravelPlanRequest) -> TripPlan:
        plan = await self.trip_planner_agent.plan_trip(request)
        plan = await self.trip_image_service.enrich_attraction_images(plan)

        # Post-planning validation: de-duplicate attractions, warn on issues
        plan, warnings = validate_trip_plan(plan, request)
        if warnings:
            plan.overall_suggestions += "\n\n📌 行程提示：\n" + "\n".join(
                f"· {w}" for w in warnings
            )
        return plan

    def get_last_traces(self) -> list[AgentTrace]:
        return self.trip_planner_agent.last_traces

    def get_image_service_status(self) -> dict:
        return self.trip_image_service.status()
