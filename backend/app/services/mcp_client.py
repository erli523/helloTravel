"""MCP integration boundary for Agent tool calls."""

import asyncio
import json
import re
from unittest.mock import patch
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings, get_settings


AMAP_MCP_TOOL_NAMES = [
    "amap_maps_text_search",
    "amap_maps_search_detail",
    "amap_maps_around_search",
    "amap_maps_direction_walking",
    "amap_maps_direction_driving",
    "amap_maps_bicycling",
    "amap_maps_direction_transit_integrated",
    "amap_maps_weather",
    "amap_maps_geo",
    "amap_maps_regeocode",
]


os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")


@dataclass
class AmapMCPToolset:
    """Shared Amap MCPTool instance used by multiple Agents."""

    settings: Settings = field(default_factory=get_settings)
    tool: Any | None = None
    expanded_tools: dict[str, Any] = field(default_factory=dict)
    startup_error: str | None = None
    degraded_reason: str | None = None
    _call_semaphore: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(4),
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.settings.amap_mcp_enabled and not self.settings.amap_rest_preferred:
            self._init_mcp_tool()

    @property
    def enabled(self) -> bool:
        return self.settings.amap_mcp_enabled and self.tool is not None

    @property
    def tool_names(self) -> list[str]:
        if self.expanded_tools:
            return list(self.expanded_tools.keys())
        return AMAP_MCP_TOOL_NAMES

    def describe(self) -> str:
        command = " ".join(self.settings.amap_mcp_command)
        if self.settings.amap_rest_preferred and self.settings.amap_mcp_enabled:
            return (
                "Amap MCP is configured, but the main planning path uses Amap REST "
                "for bounded latency. Set AMAP_REST_PREFERRED=false to route tool "
                f"calls through MCP via `{command}`."
            )
        if self.settings.amap_rest_preferred and self.settings.amap_api_key:
            return "Amap REST preferred for supported tools; MCP is not enabled."
        if self.degraded_reason:
            return (
                "Amap MCP is enabled but currently degraded; supported tools use "
                f"bounded REST fallback. Reason: {self.degraded_reason}"
            )
        if self.enabled:
            return f"Amap MCP enabled via `{command}` with {len(self.tool_names)} tools."
        if self.startup_error:
            return f"Amap MCP unavailable, using mock data. Reason: {self.startup_error}"
        return "Amap MCP disabled by AMAP_MCP_ENABLED=false, using mock data."

    def _init_mcp_tool(self) -> None:
        if not self.settings.amap_api_key:
            self.startup_error = "AMAP_API_KEY is not configured."
            return

        try:
            from hello_agents.tools import MCPTool

            with patch("builtins.print", lambda *args, **kwargs: None):
                self.tool = MCPTool(
                    name=self.settings.amap_mcp_name,
                    server_command=self.settings.amap_mcp_command,
                    env=self._mcp_env(),
                    auto_expand=True,
                )
            expanded = self.tool.get_expanded_tools()
            self.expanded_tools = {
                item.name: item for item in expanded
            } if isinstance(expanded, list) else dict(expanded)
        except Exception as exc:  # pragma: no cover - depends on local MCP runtime.
            self.tool = None
            self.expanded_tools = {}
            self.startup_error = str(exc)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an expanded MCP tool when available, otherwise return mock metadata."""

        if self.settings.amap_mcp_enabled and self.settings.amap_rest_preferred:
            rest_result = await self._call_amap_rest(tool_name, arguments)
            if rest_result is not None:
                return {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "status": "ok",
                    "source": "amap_rest",
                    "result": rest_result,
                }

        if not self.enabled:
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "status": "mocked",
                "message": self.describe(),
            }

        if self.degraded_reason:
            return await self._rest_fallback(
                tool_name,
                arguments,
                fallback_status="degraded",
                fallback_message=(
                    "MCP was degraded after a previous runtime failure; "
                    f"using bounded Amap REST fallback. Reason: {self.degraded_reason}"
                ),
            )

        tool = self.expanded_tools.get(tool_name)
        if tool is None:
            return await self._rest_fallback(
                tool_name,
                arguments,
                fallback_status="missing_tool",
                fallback_message=(
                    f"MCP tool `{tool_name}` was not expanded by the server; "
                    "used bounded Amap REST fallback instead."
                ),
            )

        try:
            async with self._call_semaphore:
                result = await asyncio.wait_for(
                    asyncio.to_thread(lambda: tool.run(arguments)),
                    timeout=self.settings.amap_mcp_tool_timeout,
                )
        except asyncio.TimeoutError:
            return await self._rest_fallback(
                tool_name,
                arguments,
                fallback_status="timeout",
                fallback_message=(
                    f"Tool {tool_name} exceeded "
                    f"{self.settings.amap_mcp_tool_timeout:.0f}s timeout."
                ),
            )
        except Exception as exc:
            if self._looks_like_encoding_failure(str(exc)):
                self.degraded_reason = str(exc)
            return await self._rest_fallback(
                tool_name,
                arguments,
                fallback_status="error",
                fallback_message=str(exc),
            )
        if self._looks_like_encoding_failure(result):
            self.degraded_reason = str(result)
            return await self._rest_fallback(
                tool_name,
                arguments,
                fallback_status="error",
                fallback_message=str(result),
            )
        if tool_name == "amap_maps_text_search" and not self._result_has_pois(result):
            return await self._rest_fallback(
                tool_name,
                arguments,
                fallback_status="empty",
                fallback_message="MCP text search returned no POI candidates.",
            )
        return {
            "tool_name": tool_name,
            "arguments": arguments,
            "status": "ok",
            "result": result,
        }

    async def _rest_fallback(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        fallback_status: str,
        fallback_message: str,
    ) -> dict[str, Any]:
        rest_result = await self._call_amap_rest(tool_name, arguments)
        if rest_result is not None:
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "status": "ok",
                "source": "amap_rest_fallback",
                "mcp_status": fallback_status,
                "message": fallback_message,
                "result": rest_result,
            }
        return {
            "tool_name": tool_name,
            "arguments": arguments,
            "status": fallback_status,
            "message": fallback_message,
        }

    async def _call_amap_rest(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not self.settings.amap_api_key:
            return None

        if tool_name == "amap_maps_text_search":
            endpoint = "https://restapi.amap.com/v3/place/text"
            city = str(arguments.get("city") or "")
            keywords = self._expand_rest_keywords(str(arguments.get("keywords") or ""))
            merged: dict[str, Any] | None = None
            seen_ids: set[str] = set()
            for keyword in keywords:
                params = {
                    "key": self.settings.amap_api_key,
                    "keywords": keyword,
                    "city": city,
                    "citylimit": "true",
                    "offset": 20,
                    "page": 1,
                    "extensions": "all",
                }
                data = await self._get_amap_json(endpoint, params)
                if not data:
                    continue
                if merged is None:
                    merged = data
                    merged["pois"] = []
                for poi in data.get("pois") or []:
                    poi_id = str(poi.get("id") or poi.get("name") or "")
                    if not poi_id or poi_id in seen_ids:
                        continue
                    seen_ids.add(poi_id)
                    merged["pois"].append(poi)
                if len(merged["pois"]) >= 12:
                    break
            return merged

        if tool_name == "amap_maps_search_detail":
            endpoint = "https://restapi.amap.com/v3/place/detail"
            params = {
                "key": self.settings.amap_api_key,
                "id": arguments.get("id", ""),
                "extensions": "all",
            }
            data = await self._get_amap_json(endpoint, params)
            if not data:
                return None
            pois = data.get("pois") or []
            if pois:
                return pois[0]
            return data

        if tool_name == "amap_maps_weather":
            endpoint = "https://restapi.amap.com/v3/weather/weatherInfo"
            params = {
                "key": self.settings.amap_api_key,
                "city": arguments.get("city", ""),
                "extensions": "all",
            }
            return await self._get_amap_json(endpoint, params)

        if tool_name in {
            "amap_maps_direction_walking",
            "amap_maps_direction_driving",
            "amap_maps_direction_transit_integrated",
        }:
            route = await self._call_amap_route_rest(tool_name, arguments)
            if route is not None:
                return route

        return None

    async def _call_amap_route_rest(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        origin = self._format_coord(arguments.get("origin"))
        destination = self._format_coord(arguments.get("destination"))
        if not origin or not destination:
            return None

        if tool_name == "amap_maps_direction_walking":
            endpoint = "https://restapi.amap.com/v3/direction/walking"
            params = {
                "key": self.settings.amap_api_key,
                "origin": origin,
                "destination": destination,
            }
            return await self._get_amap_json(endpoint, params)

        if tool_name == "amap_maps_direction_driving":
            endpoint = "https://restapi.amap.com/v3/direction/driving"
            params = {
                "key": self.settings.amap_api_key,
                "origin": origin,
                "destination": destination,
                "strategy": 10,
                "extensions": "base",
            }
            return await self._get_amap_json(endpoint, params)

        endpoint = "https://restapi.amap.com/v3/direction/transit/integrated"
        params = {
            "key": self.settings.amap_api_key,
            "origin": origin,
            "destination": destination,
            "city": arguments.get("city") or arguments.get("city1") or "",
            "cityd": arguments.get("cityd") or arguments.get("city2") or arguments.get("city") or "",
            "strategy": 0,
            "nightflag": 0,
            "extensions": "base",
        }
        return await self._get_amap_json(endpoint, params)

    @staticmethod
    def _format_coord(value: Any) -> str | None:
        if isinstance(value, str) and "," in value:
            return value.strip()
        if isinstance(value, dict):
            longitude = value.get("longitude") or value.get("lng")
            latitude = value.get("latitude") or value.get("lat")
            if longitude is not None and latitude is not None:
                return f"{longitude},{latitude}"
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return f"{value[0]},{value[1]}"
        return None

    def _expand_rest_keywords(self, keyword: str) -> list[str]:
        keyword = keyword.strip()
        if keyword in {"景点", "旅游景点", "landmark", "local culture"}:
            return ["景点", "旅游景点", "风景名胜", "公园", "博物馆"]
        if keyword in {"museum", "文化", "历史文化"}:
            return ["博物馆", "纪念馆", "文化馆", "景点", "风景名胜"]
        if keyword in {"park", "自然", "自然风光"}:
            return ["公园", "景点", "风景名胜", "湿地公园"]
        if "酒店" in keyword or "宾馆" in keyword or "住宿" in keyword:
            return [keyword, "酒店", "宾馆", "住宿"]
        if "美食" in keyword or "餐厅" in keyword or "小吃" in keyword:
            return [keyword, "餐厅", "小吃", "特色美食"]
        return [keyword]

    async def _get_amap_json(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.amap_mcp_tool_timeout
            ) as client:
                response = await client.get(endpoint, params=params)
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        data = response.json()
        if not isinstance(data, dict) or data.get("status") != "1":
            return None
        return data

    def _looks_like_encoding_failure(self, result: Any) -> bool:
        if not isinstance(result, str):
            return False
        return "codec can't encode" in result or "UnicodeEncodeError" in result

    def _result_has_pois(self, result: Any) -> bool:
        payload: dict[str, Any] | None = None
        if isinstance(result, dict):
            payload = result
        elif isinstance(result, str):
            match = re.search(r"\{.*\}", result, flags=re.S)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    payload = parsed
        if payload is None:
            return True
        pois = payload.get("pois")
        return isinstance(pois, list) and len(pois) > 0

    def _mcp_env(self) -> dict[str, str]:
        return {
            "AMAP_API_KEY": self.settings.amap_api_key,
            "AMAP_MAPS_API_KEY": self.settings.amap_api_key,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "NO_COLOR": "1",
        }

class MCPClient(AmapMCPToolset):
    """Backward-compatible name for the project MCP boundary."""
