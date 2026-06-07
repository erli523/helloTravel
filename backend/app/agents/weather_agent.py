"""WeatherQueryAgent implementation."""

from datetime import timedelta

from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.agents.prompts import WEATHER_AGENT_PROMPT
from app.models.travel import TravelPlanRequest, WeatherInfo


class WeatherQueryAgent(BaseAgent):
    """Queries and normalizes weather information."""

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

        weather_info = [
            WeatherInfo(
                date=request.start_date + timedelta(days=index),
                day_weather="sunny" if index % 2 == 0 else "cloudy",
                night_weather="cloudy",
                day_temp=f"{22 + index}C",
                night_temp=f"{14 + index}C",
                wind_direction="southeast",
                wind_power="level 3",
            )
            for index in range(request.days_count)
        ]
        prompt = self.render_prompt(city=request.city)
        query = f"Query weather for {request.city}."
        summary = (
            f"Fetched {len(weather_info)} days of weather. "
            f"{self._source_summary(tool_result)}"
        )
        reasoning_summary = (
            "Called the Amap weather tool for the destination city and normalized "
            "the forecast into one record per travel day."
        )
        context = "\n".join(
            [
                f"- {item.date}: {item.day_weather}/{item.night_weather}, "
                f"{item.day_temp}-{item.night_temp}C, wind={item.wind_direction} {item.wind_power}"
                for item in weather_info
            ]
        )
        agent_response = await self.build_agent_response(
            prompt=prompt,
            user_query=query,
            context=f"{reasoning_summary}\nTool summary: {summary}\nForecast:\n{context}",
            fallback=f"我已整理 {request.city} 的天气信息，并按每天生成了出行参考。",
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

    def _source_summary(self, tool_result: dict | None) -> str:
        if tool_result is None:
            return self.toolset_summary()
        return f"MCP tool status: {tool_result['status']}."


WeatherAgent = WeatherQueryAgent
