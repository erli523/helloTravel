"""Service boundary for travel planning."""

from app.agents.base_agent import AgentTrace
from app.agents.trip_planner_agent import TripPlannerAgent
from app.models.travel import TravelPlanRequest, TripPlan


class PlannerService:
    """Coordinates API layer and the multi-agent planning workflow."""

    def __init__(self) -> None:
        self.trip_planner_agent = TripPlannerAgent()

    async def create_plan(self, request: TravelPlanRequest) -> TripPlan:
        return await self.trip_planner_agent.plan_trip(request)

    def get_last_traces(self) -> list[AgentTrace]:
        return self.trip_planner_agent.last_traces
