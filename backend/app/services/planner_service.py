"""Service boundary for travel planning."""

import asyncio

from app.agents.attraction_agent import AttractionSearchAgent
from app.agents.base_agent import AgentTrace
from app.agents.food_agent import FoodRecommendationAgent
from app.agents.hotel_agent import HotelAgent
from app.agents.itinerary_agent import PlannerAgent
from app.agents.trip_planner_agent import TripPlannerAgent
from app.agents.weather_agent import WeatherQueryAgent
from app.config import get_settings
from app.models.travel import TravelPlanRequest, TripPlan
from app.services.trip_image_service import TripImageService
from app.services.validators import validate_trip_plan


class PlannerService:
    """Coordinates API layer and the multi-agent planning workflow."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.trip_planner_agent = TripPlannerAgent()
        self.trip_image_service = TripImageService()

    async def create_plan(self, request: TravelPlanRequest) -> TripPlan:
        plan_task = asyncio.create_task(self.trip_planner_agent.plan_trip(request))
        done, pending = await asyncio.wait(
            {plan_task},
            timeout=self.settings.planning_timeout,
        )
        if pending:
            plan_task.cancel()
            plan = await self._create_local_fallback_plan(request)
            plan.overall_suggestions += (
                "\n\n外部服务响应时间过长，系统已使用本地候选数据生成可用行程；"
                "建议稍后网络稳定时重新生成以获取更多实时 POI、酒店和图片信息。"
            )
        else:
            plan = plan_task.result()
        plan = await self.trip_image_service.enrich_attraction_images(plan)

        # Post-planning validation: de-duplicate attractions, warn on issues
        plan, warnings = validate_trip_plan(plan, request)
        if warnings:
            plan.overall_suggestions += "\n\n📌 行程提示：\n" + "\n".join(
                f"· {w}" for w in warnings
            )
        return plan

    async def _create_local_fallback_plan(self, request: TravelPlanRequest) -> TripPlan:
        attraction_agent = AttractionSearchAgent()
        weather_agent = WeatherQueryAgent()
        hotel_agent = HotelAgent()
        food_agent = FoodRecommendationAgent()
        planner_agent = PlannerAgent()

        attraction_result, weather_result, hotel_result, food_result = await asyncio.gather(
            attraction_agent.run(request),
            weather_agent.run(request),
            hotel_agent.run(request),
            food_agent.run(request),
        )
        planner_result = await planner_agent.run(
            request=request,
            attractions=attraction_result.data,
            weather_info=weather_result.data,
            hotels=hotel_result.data,
            meals=food_result.data,
            planner_query="Local fallback plan after external service timeout.",
        )
        self.trip_planner_agent.last_traces = [
            attraction_result.trace,
            weather_result.trace,
            hotel_result.trace,
            food_result.trace,
            planner_result.trace,
        ]
        return planner_result.data

    def get_last_traces(self) -> list[AgentTrace]:
        return self.trip_planner_agent.last_traces

    def get_last_context(self) -> dict:
        return self.trip_planner_agent.last_context

    def get_image_service_status(self) -> dict:
        return self.trip_image_service.status()
