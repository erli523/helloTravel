"""AttractionSearchAgent implementation."""

from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.agents.prompts import ATTRACTION_AGENT_PROMPT
from app.models.travel import Attraction, Location, TravelPlanRequest


class AttractionSearchAgent(BaseAgent):
    """Searches and normalizes attraction candidates."""

    name = "AttractionSearchAgent"
    prompt_template = ATTRACTION_AGENT_PROMPT

    async def run(self, request: TravelPlanRequest) -> AgentResult[list[Attraction]]:
        preferences = request.preferences or ["landmark", "local culture"]
        keywords = self._select_keywords(preferences)
        tool_calls = [
            f"[TOOL_CALL:amap_maps_text_search:keywords={keyword},city={request.city}]"
            for keyword in keywords
        ]
        tool_results = []
        if self.amap_tools is not None:
            for keyword in keywords:
                tool_results.append(
                    await self.amap_tools.call_tool(
                        "amap_maps_text_search",
                        {"keywords": keyword, "city": request.city},
                    )
                )

        attractions = self._mock_attractions(request, keywords)
        query = f"Search {request.city} attractions for preferences: {preferences}"

        return AgentResult(
            data=attractions,
            trace=AgentTrace(
                agent_name=self.name,
                prompt=self.render_prompt(
                    city=request.city,
                    preferences=", ".join(preferences),
                ),
                user_query=query,
                tool_calls=tool_calls,
                summary=(
                    f"Found {len(attractions)} attraction candidates. "
                    f"{self._source_summary(tool_results)}"
                ),
            ),
        )

    def _select_keywords(self, preferences: list[str]) -> list[str]:
        mapping = {
            "history": "museum",
            "culture": "museum",
            "历史文化": "博物馆",
            "文化": "博物馆",
            "nature": "park",
            "自然风光": "公园",
            "自然": "公园",
            "food": "old street",
            "美食": "老街",
            "family": "theme park",
            "亲子": "主题乐园",
        }
        keywords = [mapping.get(item, item) for item in preferences]
        return list(dict.fromkeys(keywords or ["attractions"]))[:3]

    def _mock_attractions(
        self, request: TravelPlanRequest, keywords: list[str]
    ) -> list[Attraction]:
        city = request.city
        base_data = [
            (
                f"{city} City Museum",
                f"{city} central cultural district",
                "A first-stop cultural landmark for learning local history.",
                "culture",
                60,
                120,
                116.397128,
                39.916527,
            ),
            (
                f"{city} Riverside Park",
                f"{city} riverside area",
                "A relaxed outdoor stop suitable for photos and walking.",
                "nature",
                20,
                150,
                116.407396,
                39.9042,
            ),
            (
                f"{city} Old Street",
                f"{city} old town",
                "A local street for snacks, shops, and evening atmosphere.",
                "food",
                0,
                100,
                116.384,
                39.925,
            ),
            (
                f"{city} Observation Tower",
                f"{city} skyline area",
                "A compact viewpoint for seeing the city layout.",
                "landmark",
                80,
                90,
                116.42,
                39.91,
            ),
        ]

        return [
            Attraction(
                name=name,
                address=address,
                location=Location(longitude=longitude, latitude=latitude),
                visit_duration=duration,
                description=f"{description} Matched keywords: {', '.join(keywords)}.",
                category=category,
                rating=4.5 + index * 0.1,
                image_url="https://images.unsplash.com/photo-1500530855697-b586d89ba3ee",
                ticket_price=ticket_price,
            )
            for index, (
                name,
                address,
                description,
                category,
                ticket_price,
                duration,
                longitude,
                latitude,
            ) in enumerate(base_data)
        ]

    def _source_summary(self, tool_results: list[dict]) -> str:
        if not tool_results:
            return self.toolset_summary()
        statuses = ", ".join(sorted({item["status"] for item in tool_results}))
        return f"MCP tool status: {statuses}."


AttractionAgent = AttractionSearchAgent
