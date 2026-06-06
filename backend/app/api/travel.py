"""Travel planning API routes."""

from fastapi import APIRouter

from app.agents.base_agent import AgentTrace
from app.models.travel import TravelPlanRequest, TravelPlanResponse
from app.services.planner_service import PlannerService
from app.services.unsplash_service import UnsplashPhoto

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


@router.get("/integrations")
async def get_integrations() -> dict:
    return {
        "unsplash": planner_service.get_image_service_status(),
        "amap_mcp": planner_service.trip_planner_agent.amap_tools.describe(),
    }


@router.get("/images/search", response_model=list[UnsplashPhoto])
async def search_images(query: str, per_page: int = 3) -> list[UnsplashPhoto]:
    unsplash_service = planner_service.trip_image_service.unsplash_service
    return await unsplash_service.search_photos(query=query, per_page=per_page)
