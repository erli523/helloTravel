"""WeatherQueryAgent implementation — parses real Amap forecast data."""

import json
import re
from datetime import timedelta
from typing import Any

from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.agents.prompts import WEATHER_AGENT_PROMPT
from app.models.travel import TravelPlanRequest, WeatherInfo


class WeatherQueryAgent(BaseAgent):
    """Queries and normalizes weather information from the Amap MCP tool."""

    name = "WeatherQueryAgent"
    prompt_template = WEATHER_AGENT_PROMPT

    async def run(self, request: TravelPlanRequest) -> AgentResult[list[WeatherInfo]]:
        tool_call = f"[TOOL_CALL:amap_maps_weather:city={request.city}]"
        tool_result = None
        if self.amap_tools is not None:
            tool_result = await self.amap_tools.call_tool(
                "amap_maps_weather",
                {"city": request.city},
            )

        # Try to parse real forecast; fall back to simulated data
        weather_info = self._parse_weather_result(tool_result, request)
        is_real = bool(weather_info)
        if not weather_info:
            weather_info = self._mock_weather(request)

        prompt = self.render_prompt(city=request.city)
        query = f"查询 {request.city} 旅行期间天气预报。"
        data_source = "高德实时预报" if is_real else "模拟数据（高德接口未返回预报）"
        summary = (
            f"获取 {len(weather_info)} 天天气（{data_source}）。"
            f"{self._source_summary(tool_result)}"
        )
        reasoning_summary = (
            "调用高德天气工具获取目的地预报，按旅行日期逐天解析"
            "天气状况、气温和风力，为行程安排提供参考。"
        )
        context = "\n".join(
            f"- {w.date}：{w.day_weather}，白天{w.day_temp}℃/夜间{w.night_temp}℃，"
            f"{w.wind_direction}风{w.wind_power}级"
            for w in weather_info
        )
        agent_response = await self.build_agent_response(
            prompt=prompt,
            user_query=query,
            context=f"{reasoning_summary}\n工具状态：{summary}\n天气详情：\n{context}",
            fallback=f"已整理 {request.city} 旅行期间天气信息，请关注出行当天实时天气。",
        )

        return AgentResult(
            data=weather_info,
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

    # ── Weather parsing ──────────────────────────────────────────────────

    def _parse_weather_result(
        self,
        tool_result: dict[str, Any] | None,
        request: TravelPlanRequest,
    ) -> list[WeatherInfo]:
        if tool_result is None or tool_result.get("status") != "ok":
            return []
        payload = self._parse_tool_payload(tool_result.get("result"))

        # Prefer multi-day forecasts
        forecasts = payload.get("forecasts") or payload.get("forecast") or []
        if forecasts and isinstance(forecasts, list):
            casts = forecasts[0].get("casts", []) if forecasts else []
            if casts:
                result = self._parse_casts(casts, request)
                if result:
                    return result

        # Fall back to current live conditions (replicated for all days)
        lives = payload.get("lives", [])
        if lives and isinstance(lives, list) and lives[0]:
            return self._parse_lives(lives[0], request)

        return []

    def _parse_casts(
        self,
        casts: list[dict[str, Any]],
        request: TravelPlanRequest,
    ) -> list[WeatherInfo]:
        cast_map: dict[str, dict[str, Any]] = {
            cast.get("date", ""): cast
            for cast in casts
            if cast.get("date")
        }
        result: list[WeatherInfo] = []
        for index in range(request.days_count):
            date = request.start_date + timedelta(days=index)
            cast = cast_map.get(str(date)) or (casts[-1] if casts else {})
            try:
                result.append(WeatherInfo(
                    date=date,
                    day_weather=str(cast.get("dayweather") or "晴"),
                    night_weather=str(cast.get("nightweather") or "多云"),
                    day_temp=str(cast.get("daytemp") or "25"),
                    night_temp=str(cast.get("nighttemp") or "15"),
                    wind_direction=str(cast.get("daywind") or "东"),
                    wind_power=str(cast.get("daypower") or "微风"),
                ))
            except Exception:
                continue
        return result

    def _parse_lives(
        self,
        live: dict[str, Any],
        request: TravelPlanRequest,
    ) -> list[WeatherInfo]:
        """Repeat current live weather across all travel days."""
        return [
            WeatherInfo(
                date=request.start_date + timedelta(days=index),
                day_weather=str(live.get("weather") or "晴"),
                night_weather=str(live.get("weather") or "多云"),
                day_temp=str(live.get("temperature") or "25"),
                night_temp=str(live.get("temperature") or "15"),
                wind_direction=str(live.get("winddirection") or "东"),
                wind_power=str(live.get("windpower") or "微风"),
            )
            for index in range(request.days_count)
        ]

    def _mock_weather(self, request: TravelPlanRequest) -> list[WeatherInfo]:
        """Simulated weather when the API is unavailable."""
        conditions = ["晴", "晴", "多云", "多云", "阴", "晴", "小雨"]
        return [
            WeatherInfo(
                date=request.start_date + timedelta(days=index),
                day_weather=conditions[index % len(conditions)],
                night_weather="多云",
                day_temp=str(22 + index % 5),
                night_temp=str(14 + index % 4),
                wind_direction="东南",
                wind_power="3",
            )
            for index in range(request.days_count)
        ]

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

    def _source_summary(self, tool_result: dict[str, Any] | None) -> str:
        if tool_result is None:
            return self.toolset_summary()
        return f"MCP工具状态：{tool_result['status']}。"


WeatherAgent = WeatherQueryAgent
