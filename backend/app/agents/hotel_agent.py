"""HotelAgent implementation."""

import asyncio
import json
import re
from typing import Any

from app.agents.attraction_agent import CITY_CENTERS
from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.agents.prompts import HOTEL_AGENT_PROMPT
from app.models.travel import Hotel, Location, TravelPlanRequest


class HotelAgent(BaseAgent):
    """Recommends real hotels around the destination center."""

    name = "HotelAgent"
    prompt_template = HOTEL_AGENT_PROMPT

    async def run(self, request: TravelPlanRequest) -> AgentResult[list[Hotel]]:
        keywords = self._hotel_keywords(request)
        tool_call = (
            "[TOOL_CALL:amap_maps_text_search:"
            f"keywords={keywords},city={request.city}]"
        )
        tool_result = None
        detail_results: list[dict[str, Any]] = []
        if self.amap_tools is not None:
            tool_result = await self.amap_tools.call_tool(
                "amap_maps_text_search",
                {"keywords": keywords, "city": request.city},
            )
            detail_results = await self._fetch_detail_results(tool_result)

        hotels = self._hotels_from_details(detail_results, request)
        if not hotels:
            hotels = self._fallback_hotels(request)

        prompt = self.render_prompt(
            city=request.city,
            accommodation=request.accommodation,
        )
        query = f"Search {request.accommodation} hotels in {request.city}."
        summary = (
            f"Recommended {len(hotels)} hotels. "
            f"{self._source_summary(tool_result, detail_results)}"
        )
        reasoning_summary = (
            "Converted accommodation level into hotel search keywords, called Amap "
            "hotel POI search, filtered hotel/lodging POIs, and normalized rating, "
            "address, coordinate, and estimated nightly cost."
        )
        context = "\n".join(
            [
                f"- {item.name}: {item.address}, rating={item.rating}, "
                f"price={item.price_range}, nightly={item.estimated_cost}"
                for item in hotels[:5]
            ]
        )
        agent_response = await self.build_agent_response(
            prompt=prompt,
            user_query=query,
            context=f"{reasoning_summary}\nTool summary: {summary}\nHotels:\n{context}",
            fallback=(
                f"我按 {request.accommodation} 住宿需求，为 {request.city} "
                f"筛选了 {len(hotels)} 个住宿候选，并估算了每晚费用。"
            ),
        )

        return AgentResult(
            data=hotels,
            trace=AgentTrace(
                agent_name=self.name,
                prompt=prompt,
                user_query=query,
                tool_calls=[tool_call],
                summary=summary,
                reasoning_summary=reasoning_summary,
                agent_response=agent_response,
            ),
        )

    def _hotel_keywords(self, request: TravelPlanRequest) -> str:
        if request.budget_level == "economy" or request.accommodation == "economy":
            return "经济型酒店"
        if request.budget_level == "premium" or request.accommodation == "premium":
            return "高档酒店"
        return "舒适型酒店"

    async def _fetch_detail_results(
        self,
        tool_result: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if self.amap_tools is None or tool_result is None:
            return []

        payload = self._parse_tool_payload(tool_result.get("result"))
        poi_ids: list[str] = []
        for poi in payload.get("pois", []):
            if not self._looks_like_hotel(poi):
                continue
            poi_id = str(poi.get("id") or "")
            if poi_id and poi_id not in poi_ids:
                poi_ids.append(poi_id)
            if len(poi_ids) >= 6:
                break

        return await asyncio.gather(
            *(
                self.amap_tools.call_tool("amap_maps_search_detail", {"id": poi_id})
                for poi_id in poi_ids
            )
        )

    def _hotels_from_details(
        self,
        detail_results: list[dict[str, Any]],
        request: TravelPlanRequest,
    ) -> list[Hotel]:
        hotels: list[Hotel] = []
        seen: set[str] = set()
        for result in detail_results:
            if result.get("status") != "ok":
                continue
            payload = self._parse_tool_payload(result.get("result"))
            if not self._looks_like_hotel(payload):
                continue
            name = str(payload.get("name") or "")
            if not name or name in seen:
                continue
            location = self._parse_location(payload.get("location"))
            if location is None:
                continue
            seen.add(name)
            nightly_cost = self._estimate_cost(payload, request)
            hotels.append(
                Hotel(
                    name=name,
                    address=str(payload.get("address") or ""),
                    location=location,
                    price_range=self._price_range(nightly_cost),
                    rating=str(payload.get("rating") or ""),
                    distance=str(payload.get("business_area") or "near city attractions"),
                    type=str(payload.get("type") or request.accommodation),
                    estimated_cost=nightly_cost,
                )
            )
        return hotels

    def _looks_like_hotel(self, poi: dict[str, Any]) -> bool:
        text = " ".join(
            str(poi.get(key) or "") for key in ("name", "type", "typecode", "address")
        )
        blocked = ("餐饮", "购物", "景点", "公司", "学校", "医院")
        if any(item in text for item in blocked):
            return False
        return any(item in text for item in ("住宿", "酒店", "宾馆", "旅馆", "饭店"))

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

    def _estimate_cost(self, payload: dict[str, Any], request: TravelPlanRequest) -> int:
        cost = payload.get("cost")
        if isinstance(cost, str) and cost.replace(".", "", 1).isdigit():
            return max(120, int(float(cost)))
        _, default_cost, _ = self._price_profile(request)
        return default_cost

    def _price_range(self, nightly_cost: int) -> str:
        low = max(100, nightly_cost - 120)
        high = nightly_cost + 180
        return f"{low}-{high} CNY/night"

    def _fallback_hotels(self, request: TravelPlanRequest) -> list[Hotel]:
        price_range, estimated_cost, hotel_type = self._price_profile(request)
        longitude, latitude = CITY_CENTERS.get(
            request.city,
            CITY_CENTERS.get(request.city.removesuffix("市"), (103.834303, 36.061089)),
        )
        return [
            Hotel(
                name=f"{request.city} {hotel_type.title()} Hotel near city center",
                address=f"{request.city} city center",
                location=Location(longitude=longitude, latitude=latitude),
                price_range=price_range,
                rating="",
                distance="city center fallback",
                type=hotel_type,
                estimated_cost=estimated_cost,
            )
        ]

    def _price_profile(self, request: TravelPlanRequest) -> tuple[str, int, str]:
        if request.budget_level == "economy":
            return "250-450 CNY/night", 320, "economy"
        if request.budget_level == "premium":
            return "900-1600 CNY/night", 1180, "premium"
        return "450-800 CNY/night", 580, "comfort"

    def _source_summary(
        self,
        tool_result: dict[str, Any] | None,
        detail_results: list[dict[str, Any]],
    ) -> str:
        if tool_result is None:
            return self.toolset_summary()
        detail_statuses = ", ".join(sorted({item["status"] for item in detail_results}))
        return f"MCP search status: {tool_result['status']}; detail status: {detail_statuses or 'none'}."
