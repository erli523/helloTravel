"""HotelAgent implementation."""

from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.agents.prompts import HOTEL_AGENT_PROMPT
from app.models.travel import Hotel, Location, TravelPlanRequest


class HotelAgent(BaseAgent):
    """Recommends hotels around planned attractions."""

    name = "HotelAgent"
    prompt_template = HOTEL_AGENT_PROMPT

    async def run(self, request: TravelPlanRequest) -> AgentResult[list[Hotel]]:
        tool_call = (
            "[TOOL_CALL:amap_maps_text_search:"
            f"keywords={request.accommodation} hotel,city={request.city}]"
        )
        price_range, estimated_cost, hotel_type = self._price_profile(request)
        hotels = [
            Hotel(
                name=f"{request.city} Central {hotel_type} Hotel",
                address=f"{request.city} central business district",
                location=Location(longitude=116.401, latitude=39.91),
                price_range=price_range,
                rating="4.6",
                distance="about 2 km from main attractions",
                type=hotel_type,
                estimated_cost=estimated_cost,
            ),
            Hotel(
                name=f"{request.city} Transit Friendly Hotel",
                address=f"{request.city} metro hub",
                location=Location(longitude=116.415, latitude=39.905),
                price_range=price_range,
                rating="4.4",
                distance="near metro line",
                type=hotel_type,
                estimated_cost=max(estimated_cost - 80, 200),
            ),
        ]

        return AgentResult(
            data=hotels,
            trace=AgentTrace(
                agent_name=self.name,
                prompt=self.render_prompt(
                    city=request.city,
                    accommodation=request.accommodation,
                ),
                user_query=f"Search {request.accommodation} hotels in {request.city}.",
                tool_calls=[tool_call],
                summary=f"Recommended {len(hotels)} hotels.",
            ),
        )

    def _price_profile(self, request: TravelPlanRequest) -> tuple[str, int, str]:
        if request.budget_level == "economy":
            return "300-500 CNY/night", 380, "economy"
        if request.budget_level == "premium":
            return "900-1600 CNY/night", 1280, "premium"
        return "500-900 CNY/night", 680, "comfort"
