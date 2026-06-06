"""Multi-agent collaboration workflow for trip planning."""

from app.agents.attraction_agent import AttractionSearchAgent
from app.agents.base_agent import AgentTrace
from app.agents.hotel_agent import HotelAgent
from app.agents.itinerary_agent import PlannerAgent
from app.agents.weather_agent import WeatherQueryAgent
from app.models.travel import TravelPlanRequest, TripPlan


class TripPlannerAgent:
    """Coordinates four specialized Agents into one planning workflow."""

    def __init__(self) -> None:
        self.attraction_agent = AttractionSearchAgent()
        self.weather_agent = WeatherQueryAgent()
        self.hotel_agent = HotelAgent()
        self.planner_agent = PlannerAgent()
        self.last_traces: list[AgentTrace] = []

    async def plan_trip(self, request: TravelPlanRequest) -> TripPlan:
        """Run the five-step collaboration process."""

        attraction_result = await self.attraction_agent.run(request)
        weather_result = await self.weather_agent.run(request)
        hotel_result = await self.hotel_agent.run(request)

        planner_query = self._build_planner_query(
            request=request,
            attraction_response=attraction_result.trace.summary,
            weather_response=weather_result.trace.summary,
            hotel_response=hotel_result.trace.summary,
        )
        planner_result = await self.planner_agent.run(
            request=request,
            attractions=attraction_result.data,
            weather_info=weather_result.data,
            hotels=hotel_result.data,
            planner_query=planner_query,
        )

        self.last_traces = [
            attraction_result.trace,
            weather_result.trace,
            hotel_result.trace,
            planner_result.trace,
        ]
        return planner_result.data

    def _build_planner_query(
        self,
        request: TravelPlanRequest,
        attraction_response: str,
        weather_response: str,
        hotel_response: str,
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

Please generate a detailed plan including daily attractions, meals,
hotel arrangement, transportation notes, practical suggestions, and budget details.
"""
