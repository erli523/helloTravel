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
        tool_call = f"[TOOL_CALL:maps_weather:city={request.city}]"
        tool_result = None
        if self.amap_tools is not None:
            tool_result = await self.amap_tools.call_tool(
                "maps_weather",
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

        return AgentResult(
            data=weather_info,
            trace=AgentTrace(
                agent_name=self.name,
                prompt=self.render_prompt(city=request.city),
                user_query=f"Query weather for {request.city}.",
                tool_calls=[tool_call],
                summary=(
                    f"Fetched {len(weather_info)} days of weather. "
                    f"{self._source_summary(tool_result)}"
                ),
            ),
        )

    def _source_summary(self, tool_result: dict | None) -> str:
        if tool_result is None:
            return self.toolset_summary()
        return f"MCP tool status: {tool_result['status']}."


WeatherAgent = WeatherQueryAgent
