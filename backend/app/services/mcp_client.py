"""MCP protocol client boundary for Agent tool calls."""


class MCPClient:
    """External tool invocation boundary."""

    async def call_tool(self, tool_name: str, payload: dict) -> dict:
        return {
            "tool_name": tool_name,
            "payload": payload,
            "status": "mocked",
        }
