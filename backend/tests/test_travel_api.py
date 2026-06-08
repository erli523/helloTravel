"""Smoke tests for travel API endpoints."""

import os

os.environ.setdefault("UNSPLASH_ENABLED", "false")
os.environ.setdefault("AMAP_MCP_ENABLED", "false")
os.environ.setdefault("LLM_ENABLED", "false")

from fastapi.testclient import TestClient

from app.agents.attraction_agent import AttractionSearchAgent
from app.agents.context_bus import PlanningContextBus
from app.agents.food_agent import FoodRecommendationAgent
from app.agents.hotel_agent import HotelAgent
from app.agents.itinerary_agent import PlannerAgent
from app.agents.trip_planner_agent import TripPlannerAgent
from app.agents.weather_agent import WeatherQueryAgent
from app.config import Settings
from app.models.travel import Attraction, DayPlan, Hotel, Location, Meal, ScheduleItem, TravelPlanRequest, TripPlan, WeatherInfo
from app.services.mcp_client import AmapMCPToolset
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
    assert all("context" in item for item in response.json())


def test_context_bus_is_exposed_after_plan() -> None:
    response = client.get("/api/travel/context")

    assert response.status_code == 200
    data = response.json()
    assert "steps" in data
    assert "decisions" in data
    assert any(item["agent_name"] == "AttractionSearchAgent" for item in data["decisions"])
    assert any(item["agent_name"] == "PlannerAgent" for item in data["steps"])


def test_integrations_status() -> None:
    response = client.get("/api/travel/integrations")

    assert response.status_code == 200
    data = response.json()
    assert "unsplash" in data
    assert "amap_mcp" in data
    assert data["unsplash"]["available"] is False
    assert data["react_debug"]["context_endpoint"] == "/api/travel/context"


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



def test_mcp_missing_expanded_tool_uses_bounded_fallback() -> None:
    import asyncio

    settings = Settings(
        AMAP_MCP_ENABLED=True,
        AMAP_REST_PREFERRED=False,
        AMAP_API_KEY="",
    )
    toolset = AmapMCPToolset(settings=settings, tool=object(), expanded_tools={})

    result = asyncio.run(
        toolset.call_tool(
            "amap_maps_text_search",
            {"keywords": "attraction", "city": "test-city"},
        )
    )

    assert result["status"] == "missing_tool"
    assert "not expanded" in result["message"]

class FakeAttractionLLM:
    class Settings:
        agent_response_timeout = 5

    settings = Settings()

    async def select_attraction_keywords(
        self,
        *,
        city: str,
        preferences: list[str],
        fallback_keywords: list[str],
    ) -> list[str]:
        return ["old town", "river viewpoint", "food street"]

    async def rank_attraction_candidates(
        self,
        *,
        city: str,
        preferences: list[str],
        candidates: list[dict],
        target_count: int,
    ) -> list[str]:
        return ["River Park", "Old Street", "Museum"]


def test_attraction_agent_uses_llm_keywords_with_rule_fallback() -> None:
    import asyncio

    agent = AttractionSearchAgent(llm_service=FakeAttractionLLM())
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-08",
        preferences=["culture", "nature", "food"],
    )
    fallback_keywords = ["museum", "park", "street"]

    keywords = asyncio.run(agent._select_keywords_with_llm(request, fallback_keywords))

    assert keywords[:3] == ["old town", "river viewpoint", "food street"]
    assert "museum" in keywords
    assert "park" in keywords


def test_attraction_agent_uses_llm_candidate_ranking_before_diversity() -> None:
    import asyncio

    agent = AttractionSearchAgent(llm_service=FakeAttractionLLM())
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-08",
        preferences=["culture"],
    )
    candidates = [
        Attraction(
            name="Museum",
            address="Test",
            location=Location(longitude=1, latitude=1),
            visit_duration=90,
            description="Museum",
            category="culture",
            rating=4.5,
        ),
        Attraction(
            name="Old Street",
            address="Test",
            location=Location(longitude=1.01, latitude=1.01),
            visit_duration=90,
            description="Old Street",
            category="culture",
            rating=4.5,
        ),
        Attraction(
            name="River Park",
            address="Test",
            location=Location(longitude=1.02, latitude=1.02),
            visit_duration=90,
            description="River Park",
            category="culture",
            rating=4.5,
        ),
    ]

    ranked = asyncio.run(
        agent._rank_attractions_with_llm(
            request=request,
            attractions=candidates,
            target_count=3,
        )
    )
    selected = agent._diversify_attractions(
        attractions=ranked,
        preferences=["culture"],
        target_count=3,
    )

    assert [item.name for item in ranked[:3]] == ["River Park", "Old Street", "Museum"]
    assert [item.name for item in selected[:3]] == ["River Park", "Old Street", "Museum"]


def test_attraction_agent_dedupes_same_complex_by_coordinates_and_name() -> None:
    agent = AttractionSearchAgent()
    first = Attraction(
        name="洪崖洞夜景观景台",
        address="重庆",
        location=Location(longitude=106.5790, latitude=29.5622),
        visit_duration=90,
        description="night view",
    )
    second = Attraction(
        name="洪崖洞民俗风貌区",
        address="重庆",
        location=Location(longitude=106.5791, latitude=29.5621),
        visit_duration=120,
        description="old street",
    )

    deduped = agent._dedupe_semantic_attractions([first, second])

    assert [item.name for item in deduped] == ["洪崖洞夜景观景台"]


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


def test_weather_agent_generates_semantic_weather_advice() -> None:
    advice = WeatherQueryAgent._weather_advice(
        [
            WeatherInfo(
                date="2026-06-07",
                day_weather="阵雨",
                night_weather="阵雨",
                day_temp=28,
                night_temp=20,
                wind_direction="东",
                wind_power="3",
            ),
            WeatherInfo(
                date="2026-06-08",
                day_weather="晴",
                night_weather="晴",
                day_temp=36,
                night_temp=25,
                wind_direction="东",
                wind_power="3",
            ),
        ]
    )

    assert "降雨" in advice
    assert "正午" in advice


class FakeFoodLLM:
    class Settings:
        agent_response_timeout = 5

    settings = Settings()

    async def select_food_keywords(
        self,
        *,
        city: str,
        preferences: list[str],
        fallback_keywords: list[str],
    ) -> list[str]:
        return ["bridge rice noodles", "tea house"]


def test_food_agent_uses_llm_keywords_with_rule_fallback() -> None:
    import asyncio

    agent = FoodRecommendationAgent(llm_service=FakeFoodLLM())
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-08",
        preferences=["food"],
    )

    keywords = asyncio.run(agent._select_keywords_with_llm(request, ["local food"]))

    assert keywords[:2] == ["bridge rice noodles", "tea house"]
    assert "local food" in keywords


class FakeHotelLLM:
    class Settings:
        agent_response_timeout = 5

    settings = Settings()

    async def select_best_hotel(
        self,
        *,
        candidates: list[dict],
        request_context: dict,
    ) -> dict[str, str]:
        return {"hotel_name": "Hotel B", "reason": "Closer to the main attraction cluster."}


def test_hotel_agent_llm_preference_is_consumed_by_planner() -> None:
    import asyncio

    context_bus = PlanningContextBus()
    agent = HotelAgent(llm_service=FakeHotelLLM(), context_bus=context_bus)
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-08",
        accommodation="comfort",
    )
    hotels = [
        Hotel(name="Hotel A", estimated_cost=300, rating="4.9"),
        Hotel(name="Hotel B", estimated_cost=350, rating="4.1"),
    ]

    selected = asyncio.run(agent._select_best_hotel_with_llm(request, hotels))
    planner = PlannerAgent(context_bus=context_bus)

    assert selected and selected["hotel_name"] == "Hotel B"
    assert [hotel.name for hotel in hotels] == ["Hotel A", "Hotel B"]
    assert context_bus.artifacts.get("preferred_hotel_name") is None
    context_bus.put_artifact("preferred_hotel_name", selected["hotel_name"])
    assert planner._select_best_hotel(hotels, []) == hotels[1]


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


def test_planner_quality_gate_repairs_overlapping_timeline() -> None:
    planner = PlannerAgent()
    timeline = [
        ScheduleItem(
            time="10:00",
            end_time="11:00",
            activity="A",
            location="A",
            item_type="attraction",
        ),
        ScheduleItem(
            time="10:45",
            end_time="11:10",
            activity="Transit",
            location="",
            item_type="transit",
        ),
        ScheduleItem(
            time="11:05",
            end_time="12:00",
            activity="B",
            location="B",
            item_type="attraction",
        ),
    ]

    repaired, notes = planner._repair_timeline(timeline)

    assert notes
    assert [item.activity for item in repaired] == ["A", "Transit", "B"]
    assert repaired[1].time == "11:00"
    assert repaired[2].time >= repaired[1].end_time
    for first, second in zip(repaired, repaired[1:]):
        assert _minutes(first.end_time) <= _minutes(second.time)


def test_default_schedule_moves_evening_attraction_after_dinner() -> None:
    planner = PlannerAgent()
    request = TravelPlanRequest(
        city="重庆",
        start_date="2026-06-07",
        end_date="2026-06-07",
    )
    attraction = Attraction(
        name="洪崖洞夜景观景台",
        address="重庆",
        location=Location(longitude=106.579, latitude=29.562),
        visit_duration=90,
        description="夜景",
    )
    timeline = planner._build_default_schedule(
        request,
        [attraction],
        [
            Meal(type="lunch", name="Lunch", estimated_cost=50),
            Meal(type="dinner", name="Dinner", estimated_cost=80),
        ],
    )
    night_item = next(item for item in timeline if item.item_type == "attraction")

    assert _minutes(night_item.time) >= 18 * 60
    assert "夜间" in night_item.activity


def test_geo_meals_avoid_cross_day_duplicate_lunches() -> None:
    planner = PlannerAgent()
    request = TravelPlanRequest(
        city="重庆",
        start_date="2026-06-07",
        end_date="2026-06-09",
    )
    meals = [
        Meal(type="lunch", name="Lunch A", location=Location(longitude=1, latitude=1)),
        Meal(type="lunch", name="Lunch B", location=Location(longitude=1.01, latitude=1)),
        Meal(type="dinner", name="Dinner A", location=Location(longitude=1, latitude=1)),
        Meal(type="dinner", name="Dinner B", location=Location(longitude=1.01, latitude=1)),
    ]
    attractions = [
        Attraction(
            name="A",
            address="A",
            location=Location(longitude=1, latitude=1),
            visit_duration=60,
            description="A",
        )
    ]

    first_day = planner._build_geo_meals(request, meals, attractions, 0)
    second_day = planner._build_geo_meals(request, meals, attractions, 1)

    assert next(meal.name for meal in first_day if meal.type == "lunch") == "Lunch A"
    assert next(meal.name for meal in second_day if meal.type == "lunch") == "Lunch B"


class FakeRouteTools:
    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        assert tool_name == "amap_maps_direction_transit_integrated"
        assert arguments["origin"] == "106.0,29.0"
        assert arguments["destination"] == "106.08,29.04"
        return {
            "status": "ok",
            "result": {
                "route": {
                    "transits": [
                        {
                            "duration": "2400",
                            "distance": "9000",
                        }
                    ]
                }
            },
        }


class CountingRouteTools(FakeRouteTools):
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        self.calls += 1
        return await super().call_tool(tool_name, arguments)


def test_planner_enriches_transit_with_amap_route_estimate() -> None:
    import asyncio

    planner = PlannerAgent(amap_tools=FakeRouteTools())
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-07",
        transportation="public transit + walking",
    )
    first = Attraction(
        name="A",
        address="A",
        location=Location(longitude=106.0, latitude=29.0),
        visit_duration=60,
        description="A",
        category="attraction",
    )
    second = Attraction(
        name="B",
        address="B",
        location=Location(longitude=106.08, latitude=29.04),
        visit_duration=60,
        description="B",
        category="attraction",
    )
    day = DayPlan(
        date=request.start_date,
        day_index=0,
        description="test",
        transportation=request.transportation,
        accommodation="",
        attractions=[first, second],
        timeline=[
            ScheduleItem(
                time="10:00",
                end_time="11:00",
                activity="Visit A",
                location="A",
                item_type="attraction",
            ),
            ScheduleItem(
                time="11:00",
                end_time="11:20",
                activity="Transit",
                location="",
                item_type="transit",
            ),
            ScheduleItem(
                time="11:50",
                end_time="12:50",
                activity="Visit B",
                location="B",
                item_type="attraction",
            ),
        ],
    )

    enriched = asyncio.run(planner._enrich_route_transits(request, [day]))[0]
    transit = next(item for item in enriched.timeline if item.item_type == "transit")

    assert transit.end_time == "11:40"
    assert "40" in transit.notes
    assert "9.0" in transit.notes


def test_planner_route_estimate_uses_request_scoped_cache() -> None:
    import asyncio

    tools = CountingRouteTools()
    planner = PlannerAgent(amap_tools=tools)
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-07",
        transportation="public transit + walking",
    )
    first = Attraction(
        name="A",
        address="A",
        location=Location(longitude=106.0, latitude=29.0),
        visit_duration=60,
        description="A",
        category="attraction",
    )
    second = Attraction(
        name="B",
        address="B",
        location=Location(longitude=106.08, latitude=29.04),
        visit_duration=60,
        description="B",
        category="attraction",
    )

    first_result = asyncio.run(planner._route_estimate(request, first, second))
    second_result = asyncio.run(planner._route_estimate(request, first, second))

    assert first_result == second_result
    assert tools.calls == 1


def test_timeline_attraction_matching_uses_activity_when_location_is_address() -> None:
    attraction = Attraction(
        name="Real Scenic Area",
        address="Address",
        location=Location(longitude=1, latitude=1),
        visit_duration=60,
        description="A",
    )
    timeline = [
        ScheduleItem(
            time="10:00",
            end_time="11:00",
            activity="Visit Real Scenic Area",
            location="Some street address",
            item_type="attraction",
        )
    ]

    matched = PlannerAgent._nearest_timeline_attraction(
        timeline,
        {"Real Scenic Area": attraction},
        start=0,
        step=1,
    )

    assert matched == attraction


def test_planner_react_loop_drives_route_action_from_observation() -> None:
    import asyncio

    context_bus = PlanningContextBus()
    planner = PlannerAgent(amap_tools=FakeRouteTools(), context_bus=context_bus)
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-07",
        transportation="public transit + walking",
    )
    first = Attraction(
        name="A",
        address="A",
        location=Location(longitude=106.0, latitude=29.0),
        visit_duration=60,
        description="A",
        category="attraction",
    )
    second = Attraction(
        name="B",
        address="B",
        location=Location(longitude=106.08, latitude=29.04),
        visit_duration=60,
        description="B",
        category="attraction",
    )
    day = DayPlan(
        date=request.start_date,
        day_index=0,
        description="test",
        transportation=request.transportation,
        accommodation="",
        attractions=[first, second],
        meals=[
            Meal(type="lunch", name="Lunch", estimated_cost=50),
            Meal(type="dinner", name="Dinner", estimated_cost=80),
        ],
        timeline=[
            ScheduleItem(
                time="10:00",
                end_time="11:00",
                activity="Visit A",
                location="A",
                item_type="attraction",
            ),
            ScheduleItem(
                time="11:00",
                end_time="11:20",
                activity="Transit",
                location="",
                notes="rule estimate",
                item_type="transit",
            ),
            ScheduleItem(
                time="11:50",
                end_time="12:50",
                activity="Visit B",
                location="B",
                item_type="attraction",
            ),
        ],
    )

    days, notes = asyncio.run(planner._run_react_planning_loop(request, [day]))
    transit = next(item for item in days[0].timeline if item.item_type == "transit")
    snapshot = context_bus.snapshot()

    assert notes == []
    assert transit.end_time == "11:40"
    assert "40" in transit.notes
    assert any(
        step["kind"] == "observation"
        and any(issue["code"] == "missing_route_estimate" for issue in step["data"]["issues"])
        for step in snapshot["steps"]
    )
    assert any(
        step["kind"] == "thought" and step["data"].get("action") == "enrich_routes"
        for step in snapshot["steps"]
    )


def test_planner_observes_duplicate_attractions_and_sparse_days() -> None:
    planner = PlannerAgent()
    request = TravelPlanRequest(
        city="重庆",
        start_date="2026-06-07",
        end_date="2026-06-08",
        transportation="public transit + walking",
    )
    first = Attraction(
        name="洪崖洞夜景观景台",
        address="重庆",
        location=Location(longitude=106.5790, latitude=29.5622),
        visit_duration=90,
        description="night",
    )
    second = Attraction(
        name="洪崖洞民俗风貌区",
        address="重庆",
        location=Location(longitude=106.5791, latitude=29.5621),
        visit_duration=90,
        description="street",
    )
    days = [
        DayPlan(
            date=request.start_date,
            day_index=0,
            description="day1",
            transportation=request.transportation,
            accommodation="",
            attractions=[first],
            meals=[],
            timeline=[],
        ),
        DayPlan(
            date=request.end_date,
            day_index=1,
            description="day2",
            transportation=request.transportation,
            accommodation="",
            attractions=[second],
            meals=[],
            timeline=[],
        ),
    ]

    issues = planner._observe_plan_quality(request, days)
    codes = {issue["code"] for issue in issues}

    assert "cross_day_duplicate_attraction" in codes
    assert "sparse_day" in codes


def test_react_loop_replaces_cross_day_duplicate_attraction() -> None:
    import asyncio

    planner = PlannerAgent()
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-08",
        transportation="public transit + walking",
    )
    first = Attraction(
        name="River Night View Deck",
        address="Test",
        location=Location(longitude=106.5790, latitude=29.5622),
        visit_duration=90,
        description="night view",
    )
    duplicate = Attraction(
        name="River Folk Block",
        address="Test",
        location=Location(longitude=106.5791, latitude=29.5621),
        visit_duration=90,
        description="same complex",
    )
    replacement = Attraction(
        name="Mountain History Street",
        address="Test",
        location=Location(longitude=106.6200, latitude=29.5800),
        visit_duration=90,
        description="different area",
    )
    days = [
        DayPlan(
            date=request.start_date,
            day_index=0,
            description="day1",
            transportation=request.transportation,
            accommodation="",
            attractions=[first],
            meals=[],
            timeline=[],
        ),
        DayPlan(
            date=request.end_date,
            day_index=1,
            description="day2",
            transportation=request.transportation,
            accommodation="",
            attractions=[duplicate],
            meals=[],
            timeline=[],
        ),
    ]

    repaired_days, notes = asyncio.run(
        planner._run_react_planning_loop(
            request,
            days,
            candidate_attractions=[first, duplicate, replacement],
        )
    )
    remaining_codes = {
        issue["code"] for issue in planner._observe_plan_quality(request, repaired_days)
    }

    assert repaired_days[1].attractions[0].name == "Mountain History Street"
    assert "cross_day_duplicate_attraction" not in remaining_codes
    assert any("Replaced duplicate" in note for note in notes)


def test_react_loop_fills_afternoon_gap_before_evening_attraction() -> None:
    import asyncio

    planner = PlannerAgent()
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-07",
        transportation="public transit + walking",
    )
    morning = Attraction(
        name="Old Street",
        address="Test",
        location=Location(longitude=106.50, latitude=29.50),
        visit_duration=90,
        description="historic street",
    )
    evening = Attraction(
        name="River Night View",
        address="Test",
        location=Location(longitude=106.55, latitude=29.52),
        visit_duration=90,
        description="night view",
    )
    afternoon = Attraction(
        name="Nearby Culture Park",
        address="Test",
        location=Location(longitude=106.51, latitude=29.505),
        visit_duration=90,
        description="daytime culture walk",
    )
    meals = [
        Meal(type="lunch", name="Lunch", estimated_cost=50),
        Meal(type="dinner", name="Dinner", estimated_cost=80),
    ]
    day = DayPlan(
        date=request.start_date,
        day_index=0,
        description="day",
        transportation=request.transportation,
        accommodation="",
        attractions=[morning, evening],
        meals=meals,
        timeline=planner._build_default_schedule(request, [morning, evening], meals),
    )

    repaired_days, notes = asyncio.run(
        planner._run_react_planning_loop(
            request,
            [day],
            candidate_attractions=[morning, evening, afternoon],
        )
    )

    assert [item.name for item in repaired_days[0].attractions] == [
        "Old Street",
        "Nearby Culture Park",
        "River Night View",
    ]
    assert any("Nearby Culture Park" in note for note in notes)


def test_react_loop_adds_local_experience_when_candidates_are_exhausted() -> None:
    import asyncio

    planner = PlannerAgent()
    request = TravelPlanRequest(
        city="Chengdu",
        start_date="2026-06-08",
        end_date="2026-06-08",
        transportation="public transit + walking",
    )
    attraction = Attraction(
        name="Jinli Old Street",
        address="Chengdu",
        location=Location(longitude=104.047, latitude=30.642),
        visit_duration=120,
        description="historic street",
    )
    meals = [
        Meal(type="lunch", name="Lunch", estimated_cost=50),
        Meal(type="dinner", name="Dinner", estimated_cost=90),
    ]
    day = DayPlan(
        date=request.start_date,
        day_index=0,
        description="day",
        transportation=request.transportation,
        accommodation="",
        attractions=[attraction],
        meals=meals,
        timeline=planner._build_default_schedule(request, [attraction], meals),
    )

    repaired_days, notes = asyncio.run(
        planner._run_react_planning_loop(
            request,
            [day],
            candidate_attractions=[attraction],
        )
    )
    repaired_day = repaired_days[0]

    assert len(repaired_day.attractions) == 3
    assert any(item.category == "就近体验" for item in repaired_day.attractions)
    assert not any(
        item.item_type in {"free", "rest"}
        and _minutes(item.end_time) - _minutes(item.time) >= 120
        for item in repaired_day.timeline
    )
    assert any("activity candidate" in note for note in notes)


def test_react_loop_replaces_duplicate_meal() -> None:
    import asyncio

    planner = PlannerAgent()
    request = TravelPlanRequest(
        city="Test",
        start_date="2026-06-07",
        end_date="2026-06-08",
        transportation="public transit + walking",
    )
    attraction = Attraction(
        name="A",
        address="A",
        location=Location(longitude=106.50, latitude=29.50),
        visit_duration=90,
        description="A",
    )
    lunch_a = Meal(type="lunch", name="Lunch A", estimated_cost=50)
    lunch_b = Meal(type="lunch", name="Lunch B", estimated_cost=55)
    dinner_a = Meal(type="dinner", name="Dinner A", estimated_cost=80)
    dinner_b = Meal(type="dinner", name="Dinner B", estimated_cost=85)
    days = [
        DayPlan(
            date=request.start_date,
            day_index=0,
            description="day1",
            transportation=request.transportation,
            accommodation="",
            attractions=[attraction],
            meals=[lunch_a, dinner_a],
            timeline=[],
        ),
        DayPlan(
            date=request.end_date,
            day_index=1,
            description="day2",
            transportation=request.transportation,
            accommodation="",
            attractions=[attraction],
            meals=[lunch_a, dinner_a],
            timeline=[],
        ),
    ]

    repaired_days, notes = asyncio.run(
        planner._run_react_planning_loop(
            request,
            days,
            candidate_attractions=[],
            candidate_meals=[lunch_a, lunch_b, dinner_a, dinner_b],
        )
    )

    assert next(meal.name for meal in repaired_days[1].meals if meal.type == "lunch") == "Lunch B"
    assert next(meal.name for meal in repaired_days[1].meals if meal.type == "dinner") == "Dinner B"
    assert "duplicate_meal" not in {
        issue["code"] for issue in planner._observe_plan_quality(request, repaired_days)
    }
    assert any("Replaced duplicate lunch" in note for note in notes)


class FakeReactLLM:
    available = True

    class Settings:
        agent_response_timeout = 5

    settings = Settings()

    async def choose_react_action(
        self,
        *,
        issues: list[dict],
        available_actions: list[str],
        executed_actions: list[str],
    ) -> str:
        assert "repair_timeline" in available_actions
        return "repair_timeline"


def test_planner_react_action_uses_rule_before_llm() -> None:
    import asyncio

    planner = PlannerAgent(llm_service=FakeReactLLM())
    issues = [
        {"code": "missing_route_estimate", "action": "enrich_routes"},
        {"code": "timeline_overlap", "action": "repair_timeline"},
    ]

    action = asyncio.run(
        planner._choose_react_action_with_llm(
            issues=issues,
            executed_actions=set(),
        )
    )

    assert action == "enrich_routes"


def test_planner_react_action_uses_llm_when_rule_cannot_decide() -> None:
    import asyncio

    planner = PlannerAgent(llm_service=FakeReactLLM())
    issues = [
        {"code": "ambiguous_quality_issue", "action": "needs_reasoning"},
    ]

    action = asyncio.run(
        planner._choose_react_action_with_llm(
            issues=issues,
            executed_actions=set(),
        )
    )

    assert action == "repair_timeline"


def test_trip_planner_computes_context_centroid_for_phase_two_agents() -> None:
    attractions = [
        Attraction(
            name="A",
            address="Test一区",
            location=Location(longitude=100.0, latitude=20.0),
            visit_duration=60,
            description="A",
        ),
        Attraction(
            name="B",
            address="Test二区",
            location=Location(longitude=102.0, latitude=22.0),
            visit_duration=60,
            description="B",
        ),
    ]

    centroid = TripPlannerAgent._compute_attraction_centroid(attractions)
    districts = TripPlannerAgent._extract_attraction_districts(attractions)

    assert centroid == {"longitude": 101.0, "latitude": 21.0}
    assert districts == ["Test一区", "Test二区"]


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
        formal_attractions = [
            attraction
            for attraction in day.attractions
            if attraction.category != "就近体验"
        ]
        assert len(formal_attractions) <= 2
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
