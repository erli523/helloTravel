"""Smoke tests for travel API endpoints."""

import os

os.environ.setdefault("UNSPLASH_ENABLED", "false")
os.environ.setdefault("AMAP_MCP_ENABLED", "false")
os.environ.setdefault("LLM_ENABLED", "false")

from fastapi.testclient import TestClient

from app.agents.attraction_agent import AttractionSearchAgent
from app.agents.food_agent import FoodRecommendationAgent
from app.agents.itinerary_agent import PlannerAgent
from app.models.travel import Attraction, DayPlan, Hotel, Location, Meal, ScheduleItem, TravelPlanRequest, TripPlan
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
    assert data["plan"]["budget"]["hotel_nights"] == 1
    assert data["plan"]["budget"]["details"]


def test_agent_traces_are_exposed_after_plan() -> None:
    response = client.get("/api/travel/agent-traces")

    assert response.status_code == 200
    agents = [item["agent_name"] for item in response.json()]
    assert agents == [
        "AttractionSearchAgent",
        "WeatherQueryAgent",
        "HotelAgent",
        "FoodRecommendationAgent",
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


def test_real_chinese_poi_types_are_kept_as_attractions() -> None:
    agent = AttractionSearchAgent()

    assert agent._looks_like_attraction(
        {
            "name": "重庆自然博物馆",
            "type": "科教文化服务;博物馆;博物馆",
            "typecode": "140100",
            "address": "重庆市北碚区",
        }
    )
    assert not agent._looks_like_attraction(
        {
            "name": "某某火锅店",
            "type": "餐饮服务;中餐厅;火锅店",
            "typecode": "050117",
            "address": "重庆市北碚区",
        }
    )


def test_multi_preferences_expand_to_diverse_or_keywords() -> None:
    agent = AttractionSearchAgent()

    keywords = agent._select_keywords(["culture", "nature", "food"])

    assert "历史文化" in keywords
    assert "风景名胜" in keywords
    assert any(item in keywords for item in ("老街", "美食街", "夜市", "步行街"))
    assert keywords.index("历史文化") < keywords.index("风景名胜")
    assert len(keywords) >= 6


def test_attraction_diversity_avoids_all_museums_for_mixed_preferences() -> None:
    agent = AttractionSearchAgent()

    def make_attraction(name: str, category: str, rating: float = 4.5) -> Attraction:
        return Attraction(
            name=name,
            address="测试城市",
            location=Location(longitude=106.0, latitude=29.0),
            visit_duration=120,
            description=category,
            category=category,
            rating=rating,
        )

    candidates = [
        make_attraction("城市博物馆", "科教文化服务;博物馆", 4.9),
        make_attraction("历史博物馆", "科教文化服务;博物馆", 4.8),
        make_attraction("自然博物馆", "科教文化服务;博物馆", 4.7),
        make_attraction("滨江公园", "风景名胜;公园广场", 4.4),
        make_attraction("古城老街", "风景名胜;特色街区", 4.3),
        make_attraction("山水观景台", "风景名胜;观景点", 4.2),
    ]

    selected = agent._diversify_attractions(
        attractions=candidates,
        preferences=["culture", "nature", "food"],
        target_count=5,
    )
    names = [item.name for item in selected]
    families = [agent._category_family(item) for item in selected]

    assert "城市博物馆" in names
    assert "滨江公园" in names or "山水观景台" in names
    assert "古城老街" in names
    assert families.count("museum") <= 2


def test_attraction_agent_rejects_cross_city_pois() -> None:
    agent = AttractionSearchAgent()

    assert agent._location_matches_city(Location(longitude=106.551556, latitude=29.563009), "重庆")
    assert not agent._location_matches_city(Location(longitude=121.473701, latitude=31.230416), "重庆")


def test_food_agent_assigns_meal_types_semantically() -> None:
    agent = FoodRecommendationAgent()

    hotpot_types = agent._meal_types_for_poi({"name": "老码头火锅", "type": "餐饮服务;火锅店"})
    noodle_types = agent._meal_types_for_poi({"name": "重庆小面", "type": "餐饮服务;面馆"})
    cafe_types = agent._meal_types_for_poi({"name": "山城咖啡甜品", "type": "餐饮服务;咖啡厅"})
    restaurant_types = agent._meal_types_for_poi({"name": "本地菜馆", "type": "餐饮服务;中餐厅"})

    assert hotpot_types == ["dinner"]
    assert "lunch" in noodle_types
    assert "snack" in cafe_types
    assert restaurant_types == ["lunch", "dinner"]


def test_schedule_gap_fill_and_time_safety() -> None:
    planner = PlannerAgent()
    schedule = [
        ScheduleItem(
            time="10:00",
            end_time="11:00",
            activity="A",
            location="A",
            notes="",
            item_type="attraction",
        ),
        ScheduleItem(
            time="11:10",
            end_time="11:00",
            activity="bad",
            location="bad",
            notes="",
            item_type="rest",
        ),
        ScheduleItem(
            time="11:30",
            end_time="12:00",
            activity="B",
            location="B",
            notes="",
            item_type="attraction",
        ),
        ScheduleItem(
            time="20:10",
            end_time="21:00",
            activity="late",
            location="late",
            notes="",
            item_type="rest",
        ),
    ]

    filled = planner._fill_schedule_gaps(schedule)

    assert [item.activity for item in filled] == ["A", "周边慢游与短暂休整", "B"]
    for item in filled:
        assert _minutes(item.end_time) > _minutes(item.time)
        assert _minutes(item.end_time) <= 20 * 60


class FakeSplitLLM:
    available = True

    class Settings:
        llm_timeout = 5

    settings = Settings()

    def __init__(self) -> None:
        self.assigned = False
        self.schedule_calls = 0

    async def assign_itinerary_days(self, *, system_prompt: str, planning_context: str) -> dict:
        self.assigned = True
        return {
            "days": [
                {
                    "day_index": 0,
                    "date": "2026-06-07",
                    "description": "test day",
                    "attraction_names": ["A"],
                    "lunch_name": "Lunch",
                    "dinner_name": "Dinner",
                }
            ],
            "hotel_name": "Hotel",
            "overall_suggestions": "ok",
        }

    async def generate_day_schedule(self, *, day_context: str) -> list[dict]:
        self.schedule_calls += 1
        return [
            {
                "time": "10:00",
                "end_time": "11:00",
                "activity": "游览：A",
                "location": "A",
                "notes": "test",
                "item_type": "attraction",
            }
        ]


def test_planner_uses_split_llm_assignment_and_schedule() -> None:
    import asyncio

    fake_llm = FakeSplitLLM()
    planner = PlannerAgent(llm_service=fake_llm)
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-07",
        preferences=["culture"],
    )
    attractions = [
        Attraction(
            name="A",
            address="A",
            location=Location(longitude=1, latitude=1),
            visit_duration=60,
            description="A",
            category="culture",
        )
    ]
    hotel = Hotel(name="Hotel", location=Location(longitude=1, latitude=1), estimated_cost=300)
    meals = [
        Meal(type="lunch", name="Lunch", estimated_cost=50),
        Meal(type="dinner", name="Dinner", estimated_cost=80),
    ]

    plan_data = asyncio.run(
        planner._llm_plan_days(request, attractions, [], [hotel], meals)
    )

    assert fake_llm.assigned
    assert fake_llm.schedule_calls == 1
    assert plan_data is not None
    assert plan_data["days"][0]["schedule"][0]["activity"] == "游览：A"


def _minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


async def _build_continuity_plan() -> TripPlan:
    request = TravelPlanRequest(
        city="北碚",
        start_date="2026-06-07",
        end_date="2026-06-09",
        travelers=2,
        budget_level="comfort",
        preferences=["culture", "nature", "food"],
        transportation="public transit + walking",
        accommodation="comfort",
    )
    attractions = [
        Attraction(
            name=f"北碚景点{i}",
            address="北碚区",
            location=Location(longitude=106.38 + i * 0.01, latitude=29.82 + i * 0.004),
            visit_duration=120,
            description="test",
            category="景点",
        )
        for i in range(6)
    ]
    meals = [
        Meal(
            type="lunch" if i % 2 == 0 else "dinner",
            name=f"北碚餐厅{i}",
            address="北碚区",
            location=Location(longitude=106.39 + i * 0.006, latitude=29.82),
            estimated_cost=60,
        )
        for i in range(6)
    ]
    hotel = Hotel(
        name="北碚中心酒店",
        address="北碚区",
        location=Location(longitude=106.395, latitude=29.82),
        estimated_cost=580,
    )
    result = await PlannerAgent().run(
        request=request,
        attractions=attractions,
        weather_info=[],
        hotels=[hotel],
        meals=meals,
        planner_query="test",
    )
    return result.data


def test_planner_keeps_schedule_continuous_and_consistent() -> None:
    import asyncio

    plan = asyncio.run(_build_continuity_plan())

    for day in plan.days:
        assert len(day.attractions) <= 2
        scheduled_attractions = {
            item.location for item in day.timeline if item.item_type == "attraction"
        }
        assert scheduled_attractions == {item.name for item in day.attractions}
        for current, nxt in zip(day.timeline, day.timeline[1:]):
            assert _minutes(nxt.time) - _minutes(current.end_time) < 90


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
