"""Smoke tests for travel API endpoints."""

import os

os.environ.setdefault("UNSPLASH_ENABLED", "false")
os.environ.setdefault("AMAP_MCP_ENABLED", "false")

from fastapi.testclient import TestClient

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
