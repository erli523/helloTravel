"""Multi-agent collaboration workflow for trip planning."""

import asyncio

from app.agents.attraction_agent import AttractionSearchAgent
from app.agents.base_agent import AgentTrace
from app.agents.food_agent import FoodRecommendationAgent
from app.agents.hotel_agent import HotelAgent
from app.agents.itinerary_agent import PlannerAgent
from app.agents.weather_agent import WeatherQueryAgent
from app.models.travel import TravelPlanRequest, TripPlan
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
        self.planner_agent = PlannerAgent(llm_service=self.llm_service)
        self.last_traces: list[AgentTrace] = []

    async def plan_trip(self, request: TravelPlanRequest) -> TripPlan:
        """Run the five-step collaboration process."""

        (
            attraction_result,
            weather_result,
            hotel_result,
            food_result,
        ) = await asyncio.gather(
            self.attraction_agent.run(request),
            self.weather_agent.run(request),
            self.hotel_agent.run(request),
            self.food_agent.run(request),
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
        return planner_result.data

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
