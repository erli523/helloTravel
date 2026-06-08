"""Travel planning API routes."""

from urllib.parse import unquote, urlparse

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.agents.base_agent import AgentTrace
from app.models.travel import TravelPlanRequest, TravelPlanResponse
from app.services.planner_service import PlannerService
from app.services.trip_image_service import ALLOWED_IMAGE_HOSTS
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


@router.get("/context")
async def get_planning_context() -> dict:
    return planner_service.get_last_context()


@router.get("/integrations")
async def get_integrations() -> dict:
    return {
        "unsplash": planner_service.get_image_service_status(),
        "amap_mcp": planner_service.trip_planner_agent.amap_tools.describe(),
        "llm": planner_service.trip_planner_agent.llm_service.status(),
        "react_debug": {
            "enabled": planner_service.settings.react_debug_enabled,
            "context_endpoint": "/api/travel/context",
        },
    }


@router.get("/images/search", response_model=list[UnsplashPhoto])
async def search_images(query: str, per_page: int = 3) -> list[UnsplashPhoto]:
    unsplash_service = planner_service.trip_image_service.unsplash_service
    return await unsplash_service.search_photos(query=query, per_page=per_page)


@router.get("/images/proxy")
async def proxy_image(url: str) -> Response:
    source_url = unquote(url)
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid image URL.")

    if parsed.netloc.lower() not in ALLOWED_IMAGE_HOSTS:
        raise HTTPException(status_code=400, detail="Image host is not allowed.")

    image_response = await _fetch_image(source_url)
    if image_response is None:
        fallback_url = await _fallback_image_url(source_url)
        if fallback_url:
            image_response = await _fetch_image(fallback_url)

    if image_response is None:
        raise HTTPException(status_code=502, detail="Image fetch failed.")

    content_type = image_response.headers.get("content-type", "image/jpeg")

    return Response(
        content=image_response.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


async def _fetch_image(source_url: str) -> httpx.Response | None:
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": "https://ditu.amap.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            image_response = await client.get(source_url, headers=headers)
            image_response.raise_for_status()
    except httpx.HTTPError:
        return None
    content_type = image_response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        return None
    return image_response


async def _fallback_image_url(source_url: str) -> str | None:
    parsed = urlparse(source_url)
    if "amap.com" not in parsed.netloc.lower() and "autonavi.com" not in parsed.netloc.lower():
        return None

    unsplash_service = planner_service.trip_image_service.unsplash_service
    if not unsplash_service.available:
        return None
    return await unsplash_service.get_photo_url("Chongqing travel landmark")
