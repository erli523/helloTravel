"""Travel planning API routes."""

from fastapi import APIRouter

from app.agents.base_agent import AgentTrace
from app.models.travel import TravelPlanRequest, TravelPlanResponse
from app.services.planner_service import PlannerService

router = APIRouter(prefix="/travel", tags=["travel"])

planner_service = PlannerService()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/plans", response_model=TravelPlanResponse)
async def create_travel_plan(request: TravelPlanRequest) -> TravelPlanResponse:
    plan = await planner_service.create_plan(request)
    return TravelPlanResponse(plan=plan)


@router.get("/agent-traces", response_model=list[AgentTrace])
async def get_agent_traces() -> list[AgentTrace]:
    return planner_service.get_last_traces()
