# Backend Overview

The backend is a FastAPI service that keeps these responsibilities separate:

```text
app/
├── agents/      # Multi-agent roles, prompts, traces, and workflow orchestration
├── api/         # FastAPI route definitions
├── models/      # Pydantic request/response/domain models
├── services/    # External service adapters and application services
├── config.py    # Environment-driven runtime settings
└── main.py      # FastAPI application entry point
```

## Important Services

- `PlannerService`: API-facing service that creates a `TripPlan` and enriches images.
- `TripPlannerAgent`: coordinates `AttractionSearchAgent`, `WeatherQueryAgent`, `HotelAgent`, and `PlannerAgent`.
- `AmapMCPToolset`: shared Amap MCP instance used by map-related Agents.
- `UnsplashService`: direct Unsplash API adapter for attraction images.
- `TripImageService`: fills missing attraction `image_url` values after the plan is generated.

## API Endpoints

- `GET /api/travel/health`
- `POST /api/travel/plans`
- `GET /api/travel/agent-traces`
- `GET /api/travel/integrations`
- `GET /api/travel/images/search?query=Beijing&per_page=3`

## Running Tests

```bash
conda activate travel_agent
cd backend
python -m pytest
```
