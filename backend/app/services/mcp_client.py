"""MCP integration boundary for Agent tool calls."""

from dataclasses import dataclass, field
from typing import Any

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


@dataclass
class AmapMCPToolset:
    """Shared Amap MCPTool instance used by multiple Agents."""

    settings: Settings = field(default_factory=get_settings)
    tool: Any | None = None
    expanded_tools: dict[str, Any] = field(default_factory=dict)
    startup_error: str | None = None

    def __post_init__(self) -> None:
        if self.settings.amap_mcp_enabled:
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

            self.tool = MCPTool(
                name=self.settings.amap_mcp_name,
                server_command=self.settings.amap_mcp_command,
                env={
                    "AMAP_API_KEY": self.settings.amap_api_key,
                    "AMAP_MAPS_API_KEY": self.settings.amap_api_key,
                },
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

        if not self.enabled:
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "status": "mocked",
                "message": self.describe(),
            }

        tool = self.expanded_tools.get(tool_name)
        if tool is None:
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "status": "missing",
                "message": f"Tool {tool_name} is not exposed by the MCP server.",
            }

        try:
            result = tool.run(arguments)
        except Exception as exc:
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "status": "error",
                "message": str(exc),
            }
        return {
            "tool_name": tool_name,
            "arguments": arguments,
            "status": "ok",
            "result": result,
        }


class MCPClient(AmapMCPToolset):
    """Backward-compatible name for the project MCP boundary."""
