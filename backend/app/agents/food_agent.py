"""FoodRecommendationAgent implementation."""

import asyncio
import json
import re
from itertools import cycle
from typing import Any

from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.models.travel import Location, Meal, TravelPlanRequest


FOOD_AGENT_PROMPT = """You are FoodRecommendationAgent, a local food expert.

Tool call format:
`[TOOL_CALL:amap_maps_text_search:keywords=local_food,city=city_name]`

Rules:
- Search real restaurants or local snack shops.
- Do not return retail stores, entertainment venues, electronics shops, or unrelated POIs.
- Prefer city-signature food and transit-friendly locations.
"""


CITY_FOOD_KEYWORDS: dict[str, list[str]] = {
    "北京": ["北京烤鸭", "炸酱面", "涮羊肉", "豆汁儿"],
    "北京市": ["北京烤鸭", "炸酱面", "涮羊肉", "豆汁儿"],
    "上海": ["本帮菜", "生煎包", "蟹黄小笼包", "红烧肉"],
    "上海市": ["本帮菜", "生煎包", "蟹黄小笼包", "红烧肉"],
    "广州": ["广式早茶", "肠粉", "叉烧包", "老火靓汤"],
    "广州市": ["广式早茶", "肠粉", "叉烧包", "老火靓汤"],
    "深圳": ["粤菜", "海鲜", "肠粉", "潮汕牛肉锅"],
    "深圳市": ["粤菜", "海鲜", "肠粉", "潮汕牛肉锅"],
    "成都": ["川菜", "火锅", "串串香", "担担面"],
    "成都市": ["川菜", "火锅", "串串香", "担担面"],
    "重庆": ["重庆火锅", "重庆小面", "江湖菜", "串串香"],
    "重庆市": ["重庆火锅", "重庆小面", "江湖菜", "串串香"],
    "西安": ["肉夹馍", "羊肉泡馍", "凉皮", "biangbiang面"],
    "西安市": ["肉夹馍", "羊肉泡馍", "凉皮", "biangbiang面"],
    "杭州": ["西湖醋鱼", "龙井虾仁", "东坡肉", "叫化鸡"],
    "杭州市": ["西湖醋鱼", "龙井虾仁", "东坡肉", "叫化鸡"],
    "南京": ["鸭血粉丝汤", "盐水鸭", "南京板鸭", "汤包"],
    "南京市": ["鸭血粉丝汤", "盐水鸭", "南京板鸭", "汤包"],
    "武汉": ["热干面", "鸭脖", "豆皮", "武昌鱼"],
    "武汉市": ["热干面", "鸭脖", "豆皮", "武昌鱼"],
    "苏州": ["苏式汤面", "蟹黄豆腐", "太湖三白", "苏式糕点"],
    "苏州市": ["苏式汤面", "蟹黄豆腐", "太湖三白", "苏式糕点"],
    "厦门": ["沙茶面", "姜母鸭", "土笋冻", "海蛎煎"],
    "厦门市": ["沙茶面", "姜母鸭", "土笋冻", "海蛎煎"],
    "桂林": ["桂林米粉", "啤酒鱼", "油茶", "荔浦芋头扣肉"],
    "桂林市": ["桂林米粉", "啤酒鱼", "油茶", "荔浦芋头扣肉"],
    "长沙": ["臭豆腐", "剁椒鱼头", "糖油粑粑", "口味虾"],
    "长沙市": ["臭豆腐", "剁椒鱼头", "糖油粑粑", "口味虾"],
    "昆明": ["过桥米线", "汽锅鸡", "云南野生菌", "鲜花饼"],
    "昆明市": ["过桥米线", "汽锅鸡", "云南野生菌", "鲜花饼"],
    "丽江": ["鸡豆凉粉", "腊排骨", "纳西烤鱼", "丽江粑粑"],
    "丽江市": ["鸡豆凉粉", "腊排骨", "纳西烤鱼", "丽江粑粑"],
    "张家界": ["土家腊肉", "米豆腐", "葛根粉", "土家酸菜"],
    "张家界市": ["土家腊肉", "米豆腐", "葛根粉", "土家酸菜"],
    "兰州": ["兰州牛肉面", "手抓羊肉", "酿皮", "甜醅子"],
    "兰州市": ["兰州牛肉面", "手抓羊肉", "酿皮", "甜醅子"],
    "青岛": ["海鲜", "青岛啤酒", "蛤蜊", "鲅鱼水饺"],
    "青岛市": ["海鲜", "青岛啤酒", "蛤蜊", "鲅鱼水饺"],
    "哈尔滨": ["锅包肉", "东北乱炖", "冰糖葫芦", "红肠"],
    "哈尔滨市": ["锅包肉", "东北乱炖", "冰糖葫芦", "红肠"],
    "乌鲁木齐": ["手抓饭", "烤全羊", "拌面", "馕"],
    "乌鲁木齐市": ["手抓饭", "烤全羊", "拌面", "馕"],
}


class FoodRecommendationAgent(BaseAgent):
    """Searches and normalizes local food recommendations."""

    name = "FoodRecommendationAgent"
    prompt_template = FOOD_AGENT_PROMPT

    async def run(self, request: TravelPlanRequest) -> AgentResult[list[Meal]]:
        keywords = self._select_keywords(request)
        tool_calls = [
            f"[TOOL_CALL:amap_maps_text_search:keywords={keyword},city={request.city}]"
            for keyword in keywords
        ]
        tool_results: list[dict[str, Any]] = []
        detail_results: list[dict[str, Any]] = []

        if self.amap_tools is not None:
            tool_results = await asyncio.gather(
                *(
                    self.amap_tools.call_tool(
                        "amap_maps_text_search",
                        {"keywords": keyword, "city": request.city},
                    )
                    for keyword in keywords
                )
            )
            detail_results = await self._fetch_detail_results(tool_results)

        meals = self._meals_from_details(detail_results)
        if not meals:
            meals = self._fallback_meals(request)

        query = f"Search local food in {request.city} for preferences: {request.preferences}"
        summary = f"Recommended {len(meals)} food stops. {self._source_summary(tool_results, detail_results)}"
        reasoning_summary = (
            "Searched city-signature food keywords, filtered POIs to restaurant/snack "
            "categories, and converted valid POIs into lunch/dinner meal options."
        )
        context = "\n".join(
            [
                f"- {item.name}: {item.address}, cost={item.estimated_cost}, {item.description}"
                for item in meals[:8]
            ]
        )
        agent_response = await self.build_agent_response(
            prompt=self.prompt_template,
            user_query=query,
            context=f"{reasoning_summary}\nTool summary: {summary}\nFood options:\n{context}",
            fallback=f"我为 {request.city} 优先筛选了当地代表性餐饮，并过滤掉购物、娱乐等无关地点。",
        )

        return AgentResult(
            data=meals,
            trace=AgentTrace(
                agent_name=self.name,
                prompt=self.prompt_template,
                user_query=query,
                tool_calls=tool_calls,
                summary=summary,
                reasoning_summary=reasoning_summary,
                agent_response=agent_response,
            ),
        )

    def _select_keywords(self, request: TravelPlanRequest) -> list[str]:
        city_keywords = CITY_FOOD_KEYWORDS.get(
            request.city,
            CITY_FOOD_KEYWORDS.get(request.city.removesuffix("市"), []),
        )
        if city_keywords:
            return city_keywords[:4]
        return [f"{request.city}特色美食", f"{request.city}小吃", f"{request.city}餐厅"]

    async def _fetch_detail_results(
        self,
        tool_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self.amap_tools is None:
            return []

        poi_ids: list[str] = []
        for result in tool_results:
            payload = self._parse_tool_payload(result.get("result"))
            for poi in payload.get("pois", []):
                if not self._looks_like_food_poi(poi):
                    continue
                poi_id = str(poi.get("id") or "")
                if poi_id and poi_id not in poi_ids:
                    poi_ids.append(poi_id)
                if len(poi_ids) >= 9:
                    break
            if len(poi_ids) >= 9:
                break

        return await asyncio.gather(
            *(
                self.amap_tools.call_tool("amap_maps_search_detail", {"id": poi_id})
                for poi_id in poi_ids
            )
        )

    def _meals_from_details(self, detail_results: list[dict[str, Any]]) -> list[Meal]:
        meal_types = cycle(["lunch", "dinner", "snack"])
        meals: list[Meal] = []
        seen: set[str] = set()
        for result in detail_results:
            if result.get("status") != "ok":
                continue
            payload = self._parse_tool_payload(result.get("result"))
            if not self._looks_like_food_poi(payload):
                continue
            name = str(payload.get("name") or "")
            if not name or name in seen:
                continue
            location = self._parse_location(payload.get("location"))
            seen.add(name)
            meals.append(
                Meal(
                    type=next(meal_types),
                    name=name,
                    address=str(payload.get("address") or ""),
                    location=location,
                    description=str(payload.get("type") or "local food"),
                    estimated_cost=self._estimate_cost(payload),
                )
            )
        return meals

    def _looks_like_food_poi(self, poi: dict[str, Any]) -> bool:
        text = " ".join(
            str(poi.get(key) or "") for key in ("name", "type", "typecode", "address")
        )
        blocked = ("购物", "体育", "休闲", "住宿", "公司", "生活服务", "汽车", "摩托", "家居", "电子")
        if any(item in text for item in blocked):
            return False
        return any(item in text for item in ("餐饮", "美食", "小吃", "面", "火锅", "羊肉", "饭", "餐厅", "菜"))

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

    def _estimate_cost(self, payload: dict[str, Any]) -> int:
        cost = payload.get("cost")
        if isinstance(cost, str) and cost.replace(".", "", 1).isdigit():
            return max(20, int(float(cost)))
        return 70

    def _fallback_meals(self, request: TravelPlanRequest) -> list[Meal]:
        names = CITY_FOOD_KEYWORDS.get(
            request.city,
            CITY_FOOD_KEYWORDS.get(
                request.city.removesuffix("市"),
                [f"{request.city}特色午餐", f"{request.city}招牌晚餐"],
            ),
        )
        meal_types = cycle(["lunch", "dinner", "snack"])
        return [
            Meal(
                type=next(meal_types),
                name=name,
                description=f"{request.city}当地特色，强烈推荐。",
                estimated_cost=70,
            )
            for name in names[:6]
        ]

    def _source_summary(
        self,
        tool_results: list[dict[str, Any]],
        detail_results: list[dict[str, Any]],
    ) -> str:
        if not tool_results:
            return self.toolset_summary()
        search_statuses = ", ".join(sorted({item["status"] for item in tool_results}))
        detail_statuses = ", ".join(sorted({item["status"] for item in detail_results}))
        return f"MCP search status: {search_statuses}; detail status: {detail_statuses or 'none'}."
