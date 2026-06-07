"""Smoke tests for travel API endpoints."""

import os

os.environ.setdefault("UNSPLASH_ENABLED", "false")
os.environ.setdefault("AMAP_MCP_ENABLED", "false")
os.environ.setdefault("LLM_ENABLED", "false")

from fastapi.testclient import TestClient

from app.agents.attraction_agent import AttractionSearchAgent
from app.models.travel import Attraction, DayPlan, Location, TravelPlanRequest, TripPlan
from app.services.trip_image_service import TripImageService
from app.main import app


client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/api/travel/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_travel_plan() -> None:
    response = client.post(
        "/api/travel/plans",
        json={
            "city": "Beijing",
            "start_date": "2026-06-06",
            "end_date": "2026-06-07",
            "travelers": 2,
            "budget_level": "comfort",
            "preferences": ["culture", "food"],
            "transportation": "public transit + walking",
            "accommodation": "comfort",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["plan"]["city"] == "Beijing"
    assert len(data["plan"]["days"]) == 2
    assert data["plan"]["budget"]["total"] > 0


def test_agent_traces_are_exposed_after_plan() -> None:
    response = client.get("/api/travel/agent-traces")

    assert response.status_code == 200
    agents = [item["agent_name"] for item in response.json()]
    assert agents == [
        "AttractionSearchAgent",
        "WeatherQueryAgent",
        "HotelAgent",
        "PlannerAgent",
    ]
    assert all("agent_response" in item for item in response.json())
    assert all("reasoning_summary" in item for item in response.json())


def test_integrations_status() -> None:
    response = client.get("/api/travel/integrations")

    assert response.status_code == 200
    data = response.json()
    assert "unsplash" in data
    assert "amap_mcp" in data
    assert data["unsplash"]["available"] is False


def test_image_search_without_key_returns_empty_list() -> None:
    response = client.get("/api/travel/images/search", params={"query": "Beijing"})

    assert response.status_code == 200
    assert response.json() == []


async def _run_attraction_agent_without_mcp() -> tuple[float, float]:
    request = TravelPlanRequest(
        city="重庆",
        start_date="2026-06-06",
        end_date="2026-06-07",
        preferences=["历史文化"],
    )
    result = await AttractionSearchAgent().run(request)
    location = result.data[0].location
    return location.longitude, location.latitude


def test_chongqing_mock_coordinates_use_chongqing_center() -> None:
    import asyncio

    longitude, latitude = asyncio.run(_run_attraction_agent_without_mcp())

    assert 106 <= longitude <= 107
    assert 29 <= latitude <= 30


class FakeUnsplashService:
    available = True

    async def get_photo_url(self, query: str) -> str:
        return "https://images.unsplash.com/photo-test"

    def status(self) -> dict:
        return {"available": True}


async def _enrich_plan_with_amap_image() -> TripPlan:
    plan = TripPlan(
        city="重庆",
        start_date="2026-06-06",
        end_date="2026-06-06",
        overall_suggestions="test",
        days=[
            DayPlan(
                date="2026-06-06",
                day_index=0,
                description="test",
                transportation="walk",
                accommodation="hotel",
                attractions=[
                    Attraction(
                        name="洪崖洞",
                        address="重庆",
                        location=Location(longitude=106.579027, latitude=29.562204),
                        visit_duration=120,
                        description="test",
                        image_url="http://store.is.autonavi.com/showpic/test",
                    )
                ],
            )
        ],
    )
    return await TripImageService(FakeUnsplashService()).enrich_attraction_images(plan)


def test_amap_image_urls_are_replaced_with_browser_safe_images() -> None:
    import asyncio

    plan = asyncio.run(_enrich_plan_with_amap_image())

    image_url = plan.days[0].attractions[0].image_url
    assert image_url is not None
    assert image_url.startswith("/api/travel/images/proxy?url=")
    assert "store.is.autonavi.com" in image_url


def test_image_proxy_rejects_untrusted_hosts() -> None:
    response = client.get(
        "/api/travel/images/proxy",
        params={"url": "https://example.com/image.jpg"},
    )

    assert response.status_code == 400
