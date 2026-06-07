"""AttractionSearchAgent implementation."""

import json
import re
from typing import Any

from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.agents.prompts import ATTRACTION_AGENT_PROMPT
from app.models.travel import Attraction, Location, TravelPlanRequest


CITY_CENTERS: dict[str, tuple[float, float]] = {
    "北京": (116.407396, 39.9042),
    "北京市": (116.407396, 39.9042),
    "上海": (121.473701, 31.230416),
    "上海市": (121.473701, 31.230416),
    "重庆": (106.551556, 29.563009),
    "重庆市": (106.551556, 29.563009),
    "成都": (104.066541, 30.572269),
    "成都市": (104.066541, 30.572269),
    "广州": (113.264385, 23.129112),
    "广州市": (113.264385, 23.129112),
    "深圳": (114.057868, 22.543099),
    "深圳市": (114.057868, 22.543099),
    "杭州": (120.15507, 30.274084),
    "杭州市": (120.15507, 30.274084),
    "西安": (108.93977, 34.341574),
    "西安市": (108.93977, 34.341574),
}


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
        tool_results: list[dict[str, Any]] = []
        detail_results: list[dict[str, Any]] = []

        if self.amap_tools is not None:
            for keyword in keywords:
                search_result = await self.amap_tools.call_tool(
                    "amap_maps_text_search",
                    {"keywords": keyword, "city": request.city},
                )
                tool_results.append(search_result)

            detail_results = await self._fetch_detail_results(tool_results)

        attractions = self._attractions_from_details(detail_results, keywords)
        if not attractions:
            attractions = self._mock_attractions(request, keywords)

        query = f"Search {request.city} attractions for preferences: {preferences}"
        prompt = self.render_prompt(
            city=request.city,
            preferences=", ".join(preferences),
        )
        summary = (
            f"Found {len(attractions)} attraction candidates. "
            f"{self._source_summary(tool_results, detail_results)}"
        )
        reasoning_summary = (
            "Selected search keywords from user preferences, called Amap POI search, "
            "then requested POI details to obtain precise coordinates and photos."
        )
        context = "\n".join(
            [
                f"- {item.name}: {item.address}, "
                f"rating={item.rating}, category={item.category}, "
                f"location=({item.location.longitude}, {item.location.latitude})"
                for item in attractions[:6]
            ]
        )
        agent_response = await self.build_agent_response(
            prompt=prompt,
            user_query=query,
            context=f"{reasoning_summary}\nTool summary: {summary}\nResults:\n{context}",
            fallback=(
                f"我根据你的偏好为 {request.city} 筛选了 {len(attractions)} 个候选景点，"
                "并优先使用高德 POI 详情中的坐标和图片信息。"
            ),
        )

        return AgentResult(
            data=attractions,
            trace=AgentTrace(
                agent_name=self.name,
                prompt=prompt,
                user_query=query,
                tool_calls=tool_calls,
                summary=summary,
                reasoning_summary=reasoning_summary,
                agent_response=agent_response,
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
            "landmark": "景点",
            "local culture": "景点",
        }
        keywords = [mapping.get(item, item) for item in preferences]
        return list(dict.fromkeys(keywords or ["景点"]))[:3]

    async def _fetch_detail_results(
        self, tool_results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if self.amap_tools is None:
            return []

        poi_ids: list[str] = []
        for result in tool_results:
            payload = self._parse_tool_payload(result.get("result"))
            for poi in payload.get("pois", []):
                poi_id = str(poi.get("id") or "")
                if poi_id and poi_id not in poi_ids:
                    poi_ids.append(poi_id)
                if len(poi_ids) >= 8:
                    break
            if len(poi_ids) >= 8:
                break

        detail_results = []
        for poi_id in poi_ids:
            detail_results.append(
                await self.amap_tools.call_tool(
                    "amap_maps_search_detail",
                    {"id": poi_id},
                )
            )
        return detail_results

    def _attractions_from_details(
        self,
        detail_results: list[dict[str, Any]],
        keywords: list[str],
    ) -> list[Attraction]:
        attractions: list[Attraction] = []
        seen_names: set[str] = set()

        for result in detail_results:
            if result.get("status") != "ok":
                continue
            payload = self._parse_tool_payload(result.get("result"))
            attraction = self._attraction_from_payload(payload, keywords)
            if attraction is None or attraction.name in seen_names:
                continue
            seen_names.add(attraction.name)
            attractions.append(attraction)

        return attractions

    def _attraction_from_payload(
        self,
        payload: dict[str, Any],
        keywords: list[str],
    ) -> Attraction | None:
        location = self._parse_location(payload.get("location"))
        if location is None:
            return None

        photos = payload.get("photos") if isinstance(payload.get("photos"), dict) else {}
        rating = self._parse_rating(payload.get("rating"))
        ticket_price = self._parse_ticket_price(payload.get("ticket_ordering"))
        category = str(payload.get("type") or "attraction").split(";")[0]

        return Attraction(
            name=str(payload.get("name") or "Unnamed attraction"),
            address=str(payload.get("address") or ""),
            location=location,
            visit_duration=120,
            description=(
                f"{category} in {payload.get('city') or 'the destination'}. "
                f"Matched keywords: {', '.join(keywords)}."
            ),
            category=category,
            rating=rating,
            image_url=photos.get("url") or None,
            ticket_price=ticket_price,
        )

    def _parse_tool_payload(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return {}

        match = re.search(r"\{.*\}", value, flags=re.S)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _parse_location(self, value: Any) -> Location | None:
        if not isinstance(value, str) or "," not in value:
            return None
        longitude_text, latitude_text = value.split(",", 1)
        try:
            return Location(
                longitude=float(longitude_text.strip()),
                latitude=float(latitude_text.strip()),
            )
        except ValueError:
            return None

    def _parse_rating(self, value: Any) -> float | None:
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return None
        return max(0, min(rating, 5))

    def _parse_ticket_price(self, value: Any) -> int:
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    def _mock_attractions(
        self, request: TravelPlanRequest, keywords: list[str]
    ) -> list[Attraction]:
        city = request.city
        center_longitude, center_latitude = CITY_CENTERS.get(
            city,
            CITY_CENTERS.get(city.removesuffix("市"), CITY_CENTERS["北京"]),
        )
        base_data = [
            (
                f"{city} City Museum",
                f"{city} central cultural district",
                "A first-stop cultural landmark for learning local history.",
                "culture",
                60,
                120,
                0.0,
                0.0,
            ),
            (
                f"{city} Riverside Park",
                f"{city} riverside area",
                "A relaxed outdoor stop suitable for photos and walking.",
                "nature",
                20,
                150,
                0.012,
                0.008,
            ),
            (
                f"{city} Old Street",
                f"{city} old town",
                "A local street for snacks, shops, and evening atmosphere.",
                "food",
                0,
                100,
                -0.014,
                0.006,
            ),
            (
                f"{city} Observation Tower",
                f"{city} skyline area",
                "A compact viewpoint for seeing the city layout.",
                "landmark",
                80,
                90,
                0.018,
                -0.01,
            ),
        ]

        return [
            Attraction(
                name=name,
                address=address,
                location=Location(
                    longitude=center_longitude + longitude_offset,
                    latitude=center_latitude + latitude_offset,
                ),
                visit_duration=duration,
                description=f"{description} Matched keywords: {', '.join(keywords)}.",
                category=category,
                rating=4.5 + index * 0.1,
                image_url=None,
                ticket_price=ticket_price,
            )
            for index, (
                name,
                address,
                description,
                category,
                ticket_price,
                duration,
                longitude_offset,
                latitude_offset,
            ) in enumerate(base_data)
        ]

    def _source_summary(
        self,
        tool_results: list[dict[str, Any]],
        detail_results: list[dict[str, Any]],
    ) -> str:
        if not tool_results:
            return self.toolset_summary()
        search_statuses = ", ".join(sorted({item["status"] for item in tool_results}))
        detail_statuses = ", ".join(sorted({item["status"] for item in detail_results}))
        if detail_statuses:
            return f"MCP search status: {search_statuses}; detail status: {detail_statuses}."
        return f"MCP search status: {search_statuses}."


AttractionAgent = AttractionSearchAgent
