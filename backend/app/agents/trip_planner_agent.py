"""Multi-agent collaboration workflow for trip planning."""

import asyncio

from app.agents.attraction_agent import AttractionSearchAgent
from app.agents.base_agent import AgentTrace
from app.agents.context_bus import PlanningContextBus
from app.agents.food_agent import FoodRecommendationAgent
from app.agents.hotel_agent import HotelAgent
from app.agents.itinerary_agent import PlannerAgent
from app.agents.weather_agent import WeatherQueryAgent
from app.models.travel import Attraction, TravelPlanRequest, TripPlan
from app.services.mcp_client import AmapMCPToolset
from app.services.llm_service import LLMService


class TripPlannerAgent:
    """Coordinates specialized Agents into one planning workflow."""

    def __init__(self) -> None:
        self.amap_tools = AmapMCPToolset()
        self.llm_service = LLMService()
        self.attraction_agent = AttractionSearchAgent(
            amap_tools=self.amap_tools,
            llm_service=self.llm_service,
        )
        self.weather_agent = WeatherQueryAgent(
            amap_tools=self.amap_tools,
            llm_service=self.llm_service,
        )
        self.hotel_agent = HotelAgent(
            amap_tools=self.amap_tools,
            llm_service=self.llm_service,
        )
        self.food_agent = FoodRecommendationAgent(
            amap_tools=self.amap_tools,
            llm_service=self.llm_service,
        )
        self.planner_agent = PlannerAgent(
            amap_tools=self.amap_tools,
            llm_service=self.llm_service,
        )
        self.last_traces: list[AgentTrace] = []
        self.last_context: dict = {}

    async def plan_trip(self, request: TravelPlanRequest) -> TripPlan:
        """Run the five-step collaboration process."""

        context_bus = PlanningContextBus()
        self._attach_context_bus(context_bus)
        context_bus.observe(
            "TripPlannerAgent",
            "Received travel planning request.",
            city=request.city,
            days=request.days_count,
            preferences=request.preferences,
            transportation=request.transportation,
        )

        attraction_result, weather_result = await self._run_phase_one_with_timeout(
            request,
            timeout=min(45.0, max(20.0, self.llm_service.settings.planning_timeout * 0.35)),
        )
        context_bus.put_artifact(
            "attraction_centroid",
            self._compute_attraction_centroid(attraction_result.data),
        )
        context_bus.put_artifact(
            "attraction_districts",
            self._extract_attraction_districts(attraction_result.data),
        )
        context_bus.result(
            "TripPlannerAgent",
            "Phase 1 completed; attraction geography is now available to hotel and food agents.",
            attractions=len(attraction_result.data),
            weather_days=len(weather_result.data),
            attraction_centroid=context_bus.artifacts.get("attraction_centroid"),
        )

        hotel_result, food_result = await asyncio.gather(
            self.hotel_agent.run(request),
            self.food_agent.run(request),
        )
        context_bus.result(
            "TripPlannerAgent",
            "Specialist agents completed in parallel.",
            attractions=len(attraction_result.data),
            weather_days=len(weather_result.data),
            hotels=len(hotel_result.data),
            meals=len(food_result.data),
        )

        planner_query = self._build_planner_query(
            request=request,
            attraction_response=attraction_result.trace.summary,
            weather_response=weather_result.trace.summary,
            hotel_response=hotel_result.trace.summary,
            food_response=food_result.trace.summary,
        )
        planner_result = await self.planner_agent.run(
            request=request,
            attractions=attraction_result.data,
            weather_info=weather_result.data,
            hotels=hotel_result.data,
            meals=food_result.data,
            planner_query=planner_query,
        )

        self.last_traces = [
            attraction_result.trace,
            weather_result.trace,
            hotel_result.trace,
            food_result.trace,
            planner_result.trace,
        ]
        self.last_context = context_bus.snapshot()
        return planner_result.data

    def _attach_context_bus(self, context_bus: PlanningContextBus) -> None:
        for agent in (
            self.attraction_agent,
            self.weather_agent,
            self.hotel_agent,
            self.food_agent,
            self.planner_agent,
        ):
            agent.set_context_bus(context_bus)

    async def _run_phase_one_with_timeout(
        self,
        request: TravelPlanRequest,
        *,
        timeout: float,
    ):
        try:
            return await asyncio.wait_for(
                asyncio.gather(
                    self.attraction_agent.run(request),
                    self.weather_agent.run(request),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            fallback_attraction_agent = AttractionSearchAgent()
            fallback_weather_agent = WeatherQueryAgent()
            return await asyncio.gather(
                fallback_attraction_agent.run(request),
                fallback_weather_agent.run(request),
            )

    @staticmethod
    def _compute_attraction_centroid(attractions: list[Attraction]) -> dict[str, float] | None:
        if not attractions:
            return None
        return {
            "longitude": sum(item.location.longitude for item in attractions) / len(attractions),
            "latitude": sum(item.location.latitude for item in attractions) / len(attractions),
        }

    @staticmethod
    def _extract_attraction_districts(attractions: list[Attraction]) -> list[str]:
        districts: list[str] = []
        for item in attractions:
            address = item.address or ""
            for suffix in ("区", "县", "市"):
                index = address.find(suffix)
                if index > 0:
                    district = address[: index + 1]
                    if district not in districts:
                        districts.append(district)
                    break
        return districts[:6]

    def _build_planner_query(
        self,
        request: TravelPlanRequest,
        attraction_response: str,
        weather_response: str,
        hotel_response: str,
        food_response: str,
    ) -> str:
        """Build the PlannerAgent query from user needs and specialist outputs."""

        preferences = ", ".join(request.preferences) or "general travel"
        budget = request.budget if request.budget is not None else request.budget_level

        return f"""
Please generate a {request.days_count}-day travel plan for {request.city}.

User requirements:
- Destination: {request.city}
- Dates: {request.start_date} to {request.end_date}
- Days: {request.days_count}
- Travelers: {request.travelers}
- Preferences: {preferences}
- Budget: {budget}
- Transportation: {request.transportation}
- Accommodation: {request.accommodation}

Attraction information:
{attraction_response}

Weather information:
{weather_response}

Hotel information:
{hotel_response}

Food information:
{food_response}

Please generate a detailed plan including daily attractions, meals,
hotel arrangement, transportation notes, practical suggestions, and budget details.
"""
