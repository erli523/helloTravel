# Amap MCP Integration

This project integrates Amap tools through the Model Context Protocol (MCP).
The integration is designed around one shared MCP server process for all map
related Agents.

## Tool Categories

| Category | Tool | Purpose |
| --- | --- | --- |
| POI search | `amap_maps_text_search` | Text search for POIs |
| POI search | `amap_maps_search_detail` | Fetch POI details |
| POI search | `amap_maps_around_search` | Nearby search |
| Route planning | `amap_maps_direction_walking_by_address` | Walking route |
| Route planning | `amap_maps_direction_driving_by_address` | Driving route |
| Route planning | `amap_maps_direction_transit_integrated_by_address` | Transit route |
| Weather | `amap_maps_weather` | Weather query |
| Geocoding | `amap_maps_geocode` | Address to coordinate |
| Geocoding | `amap_maps_regeocode` | Coordinate to address |

## MCPTool Creation

The project uses the installed `hello-agents` package. In this version the
constructor parameters are `server_command` and `server_args`.

```python
from hello_agents.tools import MCPTool
from app.config import get_settings

settings = get_settings()

mcp_tool = MCPTool(
    name="amap",
    server_command=["npx", "-y", "@sugarforever/amap-mcp-server"],
    env={"AMAP_API_KEY": settings.amap_api_key},
    auto_expand=True,
)
```

With `auto_expand=True`, HelloAgents discovers the tools exposed by the MCP
server and creates independent tools such as `amap_maps_text_search` and
`amap_maps_weather`.

## Shared MCP Instance

`TripPlannerAgent` creates one `AmapMCPToolset` instance and passes it to:

- `AttractionSearchAgent`
- `WeatherQueryAgent`
- `HotelAgent`
- `FoodRecommendationAgent`
- `PlannerAgent`

`PlannerAgent` also receives the shared toolset so it can enrich timeline
transit blocks with Amap walking, driving, or integrated transit route
estimates. If MCP is unavailable or slow, the same boundary can fall back to
Amap REST for supported tools.

Source files:

- `backend/app/services/mcp_client.py`
- `backend/app/agents/trip_planner_agent.py`
- `backend/app/agents/attraction_agent.py`
- `backend/app/agents/weather_agent.py`
- `backend/app/agents/hotel_agent.py`

## Runtime Configuration

Set these values in `backend/.env`:

```env
AMAP_API_KEY=your-amap-api-key
AMAP_MCP_ENABLED=true
AMAP_MCP_NAME=amap
AMAP_MCP_RUNNER=npx
AMAP_MCP_PACKAGE=@sugarforever/amap-mcp-server
AMAP_REST_PREFERRED=false
```

The project default keeps MCP enabled and prefers MCP tool calls. For local
unit tests or offline development, set `AMAP_MCP_ENABLED=false` to use fallback
data without starting the MCP runtime.

## Tool Call Flow

1. Agent emits a marker such as:

```text
[TOOL_CALL:amap_maps_text_search:keywords=attractions,city=Beijing]
```

2. HelloAgents parses the tool name and arguments.
3. The expanded `MCPTool` sends a JSON-RPC `tools/call` message to the MCP
   server over stdio.
4. The MCP server calls the Amap HTTP API with `AMAP_API_KEY`.
5. The MCP server returns the result through stdout.
6. The Agent receives the tool result and continues planning.
