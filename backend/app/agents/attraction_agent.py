"""AttractionSearchAgent implementation."""

import asyncio
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
    "北碚": (106.395593, 29.805197),
    "北碚区": (106.395593, 29.805197),
    "重庆北碚": (106.395593, 29.805197),
    "南充": (106.110698, 30.837793),
    "南充市": (106.110698, 30.837793),
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
        if len(attractions) < max(4, request.days_count * 2):
            attractions.extend(
                self._attractions_from_search_results(
                    tool_results=tool_results,
                    keywords=keywords,
                    existing_names={item.name for item in attractions},
                    limit=max(6, request.days_count * 2),
                )
            )
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
            # English preferences
            "history": "博物馆",
            "culture": "博物馆",
            "nature": "公园",
            "food": "景点",
            "family": "主题乐园",
            "landmark": "地标景点",
            "local culture": "地标景点",
            "shopping": "商业街",
            "night": "夜景",
            "photography": "风景区",
            "sports": "体育公园",
            "art": "美术馆",
            "architecture": "建筑景观",
            "beach": "海滨",
            "mountain": "山岳景区",
            # Chinese preferences
            "历史文化": "博物馆",
            "文化": "博物馆",
            "自然风光": "公园",
            "自然": "公园",
            "美食": "景点",
            "购物": "商业街",
            "亲子": "主题乐园",
            "夜游": "夜景",
            "摄影": "风景区",
            "网红": "网红景点",
            "古镇": "古镇",
            "寺庙": "寺庙",
            "山水": "风景区",
            "艺术": "美术馆",
            "休闲": "公园",
        }
        keywords = [mapping.get(item, item) for item in preferences]
        if "景点" not in keywords:
            keywords.append("景点")
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

        return await asyncio.gather(
            *(
                self.amap_tools.call_tool(
                    "amap_maps_search_detail",
                    {"id": poi_id},
                )
                for poi_id in poi_ids
            )
        )

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
            if not self._looks_like_attraction(payload):
                continue
            attraction = self._attraction_from_payload(payload, keywords)
            if attraction is None or attraction.name in seen_names:
                continue
            seen_names.add(attraction.name)
            attractions.append(attraction)

        return attractions

    def _attractions_from_search_results(
        self,
        *,
        tool_results: list[dict[str, Any]],
        keywords: list[str],
        existing_names: set[str],
        limit: int,
    ) -> list[Attraction]:
        attractions: list[Attraction] = []
        for result in tool_results:
            payload = self._parse_tool_payload(result.get("result"))
            for poi in payload.get("pois", []):
                if not self._looks_like_attraction(poi):
                    continue
                attraction = self._attraction_from_payload(poi, keywords)
                if attraction is None or attraction.name in existing_names:
                    continue
                existing_names.add(attraction.name)
                attractions.append(attraction)
                if len(existing_names) >= limit:
                    return attractions
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

    def _looks_like_attraction(self, payload: dict[str, Any]) -> bool:
        text = " ".join(
            str(payload.get(key) or "") for key in ("name", "type", "typecode", "address")
        )
        blocked = (
            "餐饮服务", "购物服务", "体育休闲服务", "生活服务", "公司",
            "电子", "汽车", "住宿服务", "餐馆", "商场", "超市",
        )
        if any(item in text for item in blocked):
            return False
        allowed = (
            "风景名胜", "科教文化", "公园", "博物馆", "纪念馆",
            "旅游景点", "景区", "自然保护区", "国家级景点",
        )
        return any(item in text for item in allowed)

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
                f"{city}博物馆",
                f"{city}市中心文化区",
                "了解当地历史文化的必打卡地标。",
                "文化",
                60,
                120,
                0.0,
                0.0,
            ),
            (
                f"{city}城市公园",
                f"{city}滨水区",
                "休闲放松、拍照散步的绝佳去处。",
                "自然",
                20,
                90,
                0.012,
                0.008,
            ),
            (
                f"{city}老街",
                f"{city}老城区",
                "品尝当地小吃、感受市井烟火气的特色街道。",
                "文化",
                0,
                90,
                -0.014,
                0.006,
            ),
            (
                f"{city}观景台",
                f"{city}制高点",
                "俯瞰城市全景的绝佳视角点。",
                "地标",
                80,
                60,
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
