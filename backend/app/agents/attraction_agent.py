"""AttractionSearchAgent implementation."""

import asyncio
import json
import re
from typing import Any

from app.agents.base_agent import AgentResult, AgentTrace, BaseAgent
from app.agents.prompts import ATTRACTION_AGENT_PROMPT
from app.models.travel import Attraction, Location, TravelPlanRequest


CITY_CENTERS: dict[str, tuple[float, float]] = {
    "北京": (116.407396, 39.9042),
    "北京市": (116.407396, 39.9042),
    "上海": (121.473701, 31.230416),
    "上海市": (121.473701, 31.230416),
    "重庆": (106.551556, 29.563009),
    "重庆市": (106.551556, 29.563009),
    "成都": (104.066541, 30.572269),
    "成都市": (104.066541, 30.572269),
    "广州": (113.264385, 23.129112),
    "广州市": (113.264385, 23.129112),
    "深圳": (114.057868, 22.543099),
    "深圳市": (114.057868, 22.543099),
    "杭州": (120.15507, 30.274084),
    "杭州市": (120.15507, 30.274084),
    "西安": (108.93977, 34.341574),
    "西安市": (108.93977, 34.341574),
    "北碚": (106.395593, 29.805197),
    "北碚区": (106.395593, 29.805197),
    "重庆北碚": (106.395593, 29.805197),
    "南充": (106.110698, 30.837793),
    "南充市": (106.110698, 30.837793),
}


class AttractionSearchAgent(BaseAgent):
    """Searches and normalizes attraction candidates."""

    name = "AttractionSearchAgent"
    prompt_template = ATTRACTION_AGENT_PROMPT
    PREFERENCE_KEYWORDS: dict[str, list[str]] = {
        "history": ["历史文化", "纪念馆", "博物馆", "古镇", "老街"],
        "culture": ["历史文化", "古镇", "纪念馆", "老街", "博物馆", "建筑景观"],
        "nature": ["风景名胜", "山水", "公园", "自然保护区", "湿地"],
        "food": ["老街", "美食街", "夜市", "步行街", "特色街区"],
        "family": ["主题乐园", "科技馆", "动物园", "公园"],
        "shopping": ["步行街", "商业街", "特色街区"],
        "night": ["夜景", "夜市", "步行街"],
        "photography": ["风景名胜", "建筑景观", "观景台"],
        "art": ["美术馆", "艺术馆", "文化中心"],
        "architecture": ["建筑景观", "历史建筑", "老街"],
        "mountain": ["山岳景区", "风景名胜", "自然保护区"],
        "landmark": ["地标景点", "风景名胜", "历史文化"],
        "local culture": ["老街", "古镇", "历史文化", "特色街区"],
        "历史文化": ["历史文化", "纪念馆", "博物馆", "古镇", "老街"],
        "文化": ["历史文化", "古镇", "纪念馆", "老街", "博物馆"],
        "自然风光": ["风景名胜", "山水", "公园", "自然保护区"],
        "自然": ["风景名胜", "山水", "公园", "自然保护区"],
        "美食": ["老街", "美食街", "夜市", "步行街", "特色街区"],
        "亲子": ["主题乐园", "科技馆", "动物园", "公园"],
        "购物": ["步行街", "商业街", "特色街区"],
        "夜游": ["夜景", "夜市", "步行街"],
        "摄影": ["风景名胜", "建筑景观", "观景台"],
        "艺术": ["美术馆", "艺术馆", "文化中心"],
        "古镇": ["古镇", "老街", "历史文化"],
        "寺庙": ["寺庙", "历史文化", "风景名胜"],
        "山水": ["山水", "风景名胜", "自然保护区"],
        "休闲": ["公园", "步行街", "特色街区"],
    }
    PREFERENCE_ALIASES: dict[str, str] = {
        "history": "culture",
        "历史文化": "culture",
        "文化": "culture",
        "local culture": "culture",
        "自然风光": "nature",
        "自然": "nature",
        "山水": "nature",
        "mountain": "nature",
        "美食": "food",
        "亲子": "family",
        "购物": "shopping",
        "夜游": "night",
        "摄影": "photography",
        "艺术": "art",
        "古镇": "culture",
        "寺庙": "culture",
        "休闲": "nature",
    }
    CITY_ATTRACTION_SUPPLEMENTS: dict[str, list[dict[str, Any]]] = {
        "重庆": [
            {
                "name": "洪崖洞民俗风貌区",
                "address": "重庆市渝中区嘉陵江滨江路",
                "location": (106.579027, 29.562204),
                "category": "传统风貌区",
                "description": "吊脚楼建筑、江景夜色和重庆小吃集中的城市风貌区。",
                "ticket_price": 0,
                "visit_duration": 90,
            },
            {
                "name": "磁器口古镇",
                "address": "重庆市沙坪坝区磁南街",
                "location": (106.44952, 29.58157),
                "category": "古镇老街",
                "description": "兼具巴渝文化、老街市井和小吃体验的历史街区。",
                "ticket_price": 0,
                "visit_duration": 120,
            },
            {
                "name": "南山一棵树观景台",
                "address": "重庆市南岸区南山风景区",
                "location": (106.59691, 29.54404),
                "category": "自然观景",
                "description": "俯瞰重庆两江与山城夜景的经典观景点。",
                "ticket_price": 30,
                "visit_duration": 90,
            },
            {
                "name": "鹅岭公园",
                "address": "重庆市渝中区鹅岭正街",
                "location": (106.53887, 29.55496),
                "category": "城市公园",
                "description": "山城中心的老牌公园，适合散步、观景和放慢节奏。",
                "ticket_price": 0,
                "visit_duration": 90,
            },
            {
                "name": "山城步道",
                "address": "重庆市渝中区中兴路",
                "location": (106.56839, 29.55284),
                "category": "历史街区",
                "description": "连接老重庆街巷、江景和市井生活的步行线路。",
                "ticket_price": 0,
                "visit_duration": 90,
            },
        ],
    }
    CITY_ATTRACTION_SUPPLEMENTS["重庆市"] = CITY_ATTRACTION_SUPPLEMENTS["重庆"]
    CITY_ATTRACTION_SUPPLEMENTS["北碚"] = [
        {
            "name": "金刚碑历史文化街区",
            "address": "重庆市北碚区北温泉街道",
            "location": (106.40747, 29.83345),
            "category": "历史街区",
            "description": "依山临水的老街区，适合感受北碚历史文化和慢行体验。",
            "ticket_price": 0,
            "visit_duration": 120,
        },
        {
            "name": "北温泉风景区",
            "address": "重庆市北碚区北温泉街道",
            "location": (106.40972, 29.82764),
            "category": "自然风景",
            "description": "北碚经典山水温泉景区，兼具自然景观和历史建筑。",
            "ticket_price": 0,
            "visit_duration": 120,
        },
        {
            "name": "缙云山国家级自然保护区",
            "address": "重庆市北碚区缙云山",
            "location": (106.37592, 29.84162),
            "category": "自然保护区",
            "description": "北碚代表性的山地自然景观，适合徒步和观景。",
            "ticket_price": 15,
            "visit_duration": 180,
        },
        {
            "name": "重庆自然博物馆",
            "address": "重庆市北碚区金华路398号",
            "location": (106.41449, 29.80377),
            "category": "博物馆",
            "description": "适合文化、亲子和自然主题的室内博物馆。",
            "ticket_price": 0,
            "visit_duration": 120,
        },
        {
            "name": "老舍旧居",
            "address": "重庆市北碚区天生路",
            "location": (106.42561, 29.82167),
            "category": "名人故居",
            "description": "了解北碚抗战文化和文学记忆的名人故居。",
            "ticket_price": 0,
            "visit_duration": 60,
        },
    ]
    CITY_ATTRACTION_SUPPLEMENTS["北碚区"] = CITY_ATTRACTION_SUPPLEMENTS["北碚"]
    CITY_ATTRACTION_SUPPLEMENTS["重庆北碚"] = CITY_ATTRACTION_SUPPLEMENTS["北碚"]

    async def run(self, request: TravelPlanRequest) -> AgentResult[list[Attraction]]:
        preferences = request.preferences or ["landmark", "local culture"]
        fallback_keywords = self._select_keywords(preferences)
        keywords = await self._select_keywords_with_llm(request, fallback_keywords)
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

        target_count = max(
            6,
            request.days_count
            * (2 if request.transportation == "public transit + walking" else 3),
        )
        attractions = self._attractions_from_details(detail_results, keywords, request.city)
        attractions.extend(
            self._attractions_from_search_results(
                tool_results=tool_results,
                keywords=keywords,
                city=request.city,
                existing_names={item.name for item in attractions},
                limit=target_count,
            )
        )
        if not attractions:
            attractions = self._mock_attractions(request, keywords)
        attractions.extend(self._supplement_attractions_for_preferences(request, attractions))
        attractions = await self._rank_attractions_with_llm(
            request=request,
            attractions=attractions,
            target_count=target_count,
        )
        attractions = self._diversify_attractions(
            attractions=attractions,
            preferences=preferences,
            target_count=target_count,
        )

        query = f"Search {request.city} attractions for preferences: {preferences}"
        prompt = self.render_prompt(
            city=request.city,
            preferences=", ".join(preferences),
        )
        summary = (
            f"Found {len(attractions)} attraction candidates. "
            f"{self._source_summary(tool_results, detail_results)}"
        )
        reasoning_summary = (
            "Selected diverse search keywords from user preferences, called Amap POI search, "
            "requested POI details, then ranked and diversified real candidates for coverage."
        )
        context = "\n".join(
            [
                f"- {item.name}: {item.address}, "
                f"rating={item.rating}, category={item.category}, "
                f"location=({item.location.longitude}, {item.location.latitude})"
                for item in attractions[:6]
            ]
        )
        agent_response = await self.build_agent_response(
            prompt=prompt,
            user_query=query,
            context=f"{reasoning_summary}\nTool summary: {summary}\nResults:\n{context}",
            fallback=(
                f"我根据你的偏好为 {request.city} 筛选了 {len(attractions)} 个候选景点，"
                "并优先使用高德 POI 详情中的坐标和图片信息。"
            ),
        )

        return AgentResult(
            data=attractions,
            trace=AgentTrace(
                agent_name=self.name,
                prompt=prompt,
                user_query=query,
                tool_calls=tool_calls,
                summary=summary,
                reasoning_summary=reasoning_summary,
                agent_response=agent_response,
            ),
        )

    async def _select_keywords_with_llm(
        self,
        request: TravelPlanRequest,
        fallback_keywords: list[str],
    ) -> list[str]:
        if self.llm_service is None:
            return fallback_keywords
        try:
            llm_keywords = await asyncio.wait_for(
                self.llm_service.select_attraction_keywords(
                    city=request.city,
                    preferences=request.preferences,
                    fallback_keywords=fallback_keywords,
                ),
                timeout=self.llm_service.settings.agent_response_timeout,
            )
        except (AttributeError, asyncio.TimeoutError):
            return fallback_keywords

        return self._merge_llm_keywords(llm_keywords, fallback_keywords)

    def _merge_llm_keywords(
        self,
        llm_keywords: list[str] | None,
        fallback_keywords: list[str],
    ) -> list[str]:
        if not llm_keywords:
            return fallback_keywords

        merged: list[str] = []
        for keyword in llm_keywords:
            clean_keyword = str(keyword).strip()
            if clean_keyword:
                merged.append(clean_keyword)

        # Keep rule keywords as safety coverage in case the LLM is too narrow.
        merged.extend(fallback_keywords)
        return list(dict.fromkeys(merged))[:8] or fallback_keywords

    async def _rank_attractions_with_llm(
        self,
        *,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        target_count: int,
    ) -> list[Attraction]:
        if self.llm_service is None or not attractions:
            return attractions

        candidates = [
            {
                "name": item.name,
                "category": item.category,
                "address": item.address,
                "rating": item.rating,
                "ticket_price": item.ticket_price,
                "tags": sorted(self._preference_tags(item)),
            }
            for item in attractions[:24]
        ]
        try:
            ranked_names = await asyncio.wait_for(
                self.llm_service.rank_attraction_candidates(
                    city=request.city,
                    preferences=request.preferences,
                    candidates=candidates,
                    target_count=target_count,
                ),
                timeout=self.llm_service.settings.agent_response_timeout,
            )
        except (AttributeError, asyncio.TimeoutError):
            return attractions

        return self._apply_llm_attraction_order(attractions, ranked_names)

    @staticmethod
    def _apply_llm_attraction_order(
        attractions: list[Attraction],
        ranked_names: list[str] | None,
    ) -> list[Attraction]:
        if not ranked_names:
            return attractions

        by_name = {item.name: item for item in attractions}
        ordered: list[Attraction] = []
        selected_names: set[str] = set()
        for name in ranked_names:
            attraction = by_name.get(str(name).strip())
            if attraction is None or attraction.name in selected_names:
                continue
            ordered.append(attraction)
            selected_names.add(attraction.name)

        ordered.extend(item for item in attractions if item.name not in selected_names)
        return ordered or attractions

    def _select_keywords(self, preferences: list[str]) -> list[str]:
        """Expand user preferences as OR-style search intents, not one narrow query."""

        keywords: list[str] = []
        for preference in preferences:
            preference_key = str(preference).strip()
            if not preference_key:
                continue
            expanded = self.PREFERENCE_KEYWORDS.get(preference_key, [preference_key])
            keywords.extend(expanded[:3])

        # Add secondary terms after the first pass so the primary preference keeps priority,
        # while later preferences still influence the candidate pool.
        for preference in preferences:
            expanded = self.PREFERENCE_KEYWORDS.get(str(preference).strip(), [])
            keywords.extend(expanded[3:5])

        keywords.extend(["风景名胜", "景点"])
        return list(dict.fromkeys(keywords or ["风景名胜", "景点"]))[:8]

    async def _fetch_detail_results(
        self, tool_results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if self.amap_tools is None:
            return []

        poi_ids: list[str] = []
        poi_groups: list[list[dict[str, Any]]] = []
        for result in tool_results:
            payload = self._parse_tool_payload(result.get("result"))
            pois = payload.get("pois", [])
            if isinstance(pois, list) and pois:
                poi_groups.append(pois)

        max_detail_count = 14
        max_group_length = max((len(group) for group in poi_groups), default=0)
        for offset in range(max_group_length):
            for group in poi_groups:
                if offset >= len(group):
                    continue
                poi = group[offset]
                poi_id = str(poi.get("id") or "")
                if poi_id and poi_id not in poi_ids:
                    poi_ids.append(poi_id)
                if len(poi_ids) >= max_detail_count:
                    break
            if len(poi_ids) >= max_detail_count:
                break

        return await asyncio.gather(
            *(
                self.amap_tools.call_tool(
                    "amap_maps_search_detail",
                    {"id": poi_id},
                )
                for poi_id in poi_ids
            )
        )

    def _attractions_from_details(
        self,
        detail_results: list[dict[str, Any]],
        keywords: list[str],
        city: str,
    ) -> list[Attraction]:
        attractions: list[Attraction] = []
        seen_names: set[str] = set()

        for result in detail_results:
            if result.get("status") != "ok":
                continue
            payload = self._parse_tool_payload(result.get("result"))
            if not self._looks_like_attraction(payload):
                continue
            attraction = self._attraction_from_payload(payload, keywords)
            if attraction is None or attraction.name in seen_names:
                continue
            if not self._location_matches_city(attraction.location, city):
                continue
            seen_names.add(attraction.name)
            attractions.append(attraction)

        return attractions

    def _attractions_from_search_results(
        self,
        *,
        tool_results: list[dict[str, Any]],
        keywords: list[str],
        city: str,
        existing_names: set[str],
        limit: int,
    ) -> list[Attraction]:
        attractions: list[Attraction] = []
        poi_groups: list[list[dict[str, Any]]] = []
        for result in tool_results:
            payload = self._parse_tool_payload(result.get("result"))
            pois = payload.get("pois", [])
            if isinstance(pois, list) and pois:
                poi_groups.append(pois)

        max_group_length = max((len(group) for group in poi_groups), default=0)
        for offset in range(max_group_length):
            for group in poi_groups:
                if offset >= len(group):
                    continue
                poi = group[offset]
                if not self._looks_like_attraction(poi):
                    continue
                attraction = self._attraction_from_payload(poi, keywords)
                if attraction is None or attraction.name in existing_names:
                    continue
                if not self._location_matches_city(attraction.location, city):
                    continue
                existing_names.add(attraction.name)
                attractions.append(attraction)
                if len(attractions) >= limit:
                    return attractions
        return attractions

    def _diversify_attractions(
        self,
        *,
        attractions: list[Attraction],
        preferences: list[str],
        target_count: int,
    ) -> list[Attraction]:
        """Prefer coverage across selected preferences and avoid one-note POI lists."""

        if not attractions:
            return []

        normalized_preferences = self._normalize_preferences(preferences)
        target_count = max(4, min(target_count, len(attractions)))
        original_order = {item.name: index for index, item in enumerate(attractions)}
        ranked = sorted(
            attractions,
            key=lambda item: (
                *self._attraction_score(item, normalized_preferences),
                -original_order.get(item.name, 0),
            ),
            reverse=True,
        )

        selected: list[Attraction] = []
        selected_names: set[str] = set()
        family_counts: dict[str, int] = {}

        def add(item: Attraction, *, strict_family_cap: bool = True) -> bool:
            if item.name in selected_names:
                return False
            family = self._category_family(item)
            if strict_family_cap and family_counts.get(family, 0) >= 2:
                return False
            selected.append(item)
            selected_names.add(item.name)
            family_counts[family] = family_counts.get(family, 0) + 1
            return True

        # First, satisfy each selected preference at least once when possible.
        for preference in normalized_preferences:
            matched = [
                item for item in ranked
                if preference in self._preference_tags(item)
                and item.name not in selected_names
            ]
            preferred_family = self._preferred_family_for_preference(preference)
            matched = sorted(
                matched,
                key=lambda item: (
                    self._category_family(item) in preferred_family,
                    self._attraction_score(item, normalized_preferences),
                ),
                reverse=True,
            )
            if matched:
                add(matched[0], strict_family_cap=False)

        # For the primary preference, add one extra but prefer a different family.
        if normalized_preferences:
            primary = normalized_preferences[0]
            for item in ranked:
                if primary not in self._preference_tags(item):
                    continue
                if add(item, strict_family_cap=True):
                    break

        # Then fill by score, keeping a soft cap on repeated families.
        for item in ranked:
            if len(selected) >= target_count:
                break
            add(item, strict_family_cap=True)

        for item in ranked:
            if len(selected) >= target_count:
                break
            add(item, strict_family_cap=False)

        return selected

    def _normalize_preferences(self, preferences: list[str]) -> list[str]:
        normalized: list[str] = []
        for preference in preferences:
            key = str(preference).strip()
            canonical = self.PREFERENCE_ALIASES.get(key, key)
            if canonical in {
                "culture",
                "nature",
                "food",
                "family",
                "shopping",
                "night",
                "photography",
                "art",
                "architecture",
            } and canonical not in normalized:
                normalized.append(canonical)
        return normalized

    def _supplement_attractions_for_preferences(
        self,
        request: TravelPlanRequest,
        attractions: list[Attraction],
    ) -> list[Attraction]:
        presets = self.CITY_ATTRACTION_SUPPLEMENTS.get(request.city)
        if not presets:
            return []

        existing_tags: set[str] = set()
        family_counts: dict[str, int] = {}
        for item in attractions:
            existing_tags.update(self._preference_tags(item))
            family = self._category_family(item)
            family_counts[family] = family_counts.get(family, 0) + 1

        wanted_tags = set(self._normalize_preferences(request.preferences))
        largest_family = max(family_counts.values(), default=0)
        pool_is_balanced = largest_family <= max(3, len(attractions) // 2)
        family_satisfied = self._preference_families_satisfied(wanted_tags, family_counts)
        if wanted_tags.issubset(existing_tags) and family_satisfied and pool_is_balanced:
            return []

        existing_names = {item.name for item in attractions}
        supplements: list[Attraction] = []
        for preset in presets:
            if preset["name"] in existing_names:
                continue
            longitude, latitude = preset["location"]
            supplements.append(
                Attraction(
                    name=preset["name"],
                    address=preset["address"],
                    location=Location(longitude=longitude, latitude=latitude),
                    visit_duration=preset["visit_duration"],
                    description=preset["description"],
                    category=preset["category"],
                    rating=4.6,
                    ticket_price=preset["ticket_price"],
                )
            )
        return supplements

    @staticmethod
    def _preferred_family_for_preference(preference: str) -> set[str]:
        mapping = {
            "nature": {"nature"},
            "food": {"food_area", "historic_street"},
            "culture": {"culture", "museum", "memorial", "historic_street"},
            "family": {"family"},
        }
        return mapping.get(preference, {preference})

    @staticmethod
    def _preference_families_satisfied(
        wanted_tags: set[str],
        family_counts: dict[str, int],
    ) -> bool:
        if "nature" in wanted_tags and family_counts.get("nature", 0) == 0:
            return False
        if "food" in wanted_tags and (
            family_counts.get("food_area", 0) + family_counts.get("historic_street", 0)
        ) == 0:
            return False
        return True

    def _preference_tags(self, attraction: Attraction) -> set[str]:
        text = self._attraction_text(attraction)
        tags: set[str] = set()
        if any(
            token in text
            for token in (
                "历史", "文化", "博物馆", "纪念馆", "古镇", "老街", "故居",
                "遗址", "旧址", "寺", "祠", "会馆", "艺术馆", "美术馆", "建筑",
                "传统", "风貌", "街区",
            )
        ):
            tags.add("culture")
        nature_tokens = (
            "山", "水", "湖", "江", "河", "公园",
            "湿地", "森林", "峡", "温泉", "保护区", "观景",
        )
        if any(token in text for token in nature_tokens) or (
            "自然" in text and "博物馆" not in text
        ):
            tags.add("nature")
        if any(token in text for token in ("老街", "夜市", "美食街", "步行街", "特色街区", "街区", "风貌区")):
            tags.add("food")
        if any(token in text for token in ("乐园", "动物园", "科技馆", "游乐", "亲子")):
            tags.add("family")
        if any(token in text for token in ("步行街", "商业街", "商圈", "购物")):
            tags.add("shopping")
        if any(token in text for token in ("夜景", "夜市", "灯光", "观景")):
            tags.add("night")
        if any(token in text for token in ("观景", "风景", "建筑", "摄影", "网红")):
            tags.add("photography")
        if any(token in text for token in ("艺术", "美术馆", "展览", "剧院")):
            tags.add("art")
        if any(token in text for token in ("建筑", "老街", "古镇", "故居", "会馆")):
            tags.add("architecture")
        return tags

    def _attraction_score(
        self,
        attraction: Attraction,
        normalized_preferences: list[str],
    ) -> tuple[float, float, float]:
        tags = self._preference_tags(attraction)
        preference_score = 0.0
        for index, preference in enumerate(normalized_preferences):
            if preference in tags:
                preference_score += 4.0 if index == 0 else 2.0
        diversity_score = min(len(tags), 3) * 0.4
        rating_score = attraction.rating or 3.5
        return preference_score + diversity_score, rating_score, -float(attraction.ticket_price or 0)

    def _category_family(self, attraction: Attraction) -> str:
        tags = self._preference_tags(attraction)
        if "food" in tags:
            return "food_area"
        if "nature" in tags and "culture" not in tags:
            return "nature"
        if "culture" in tags:
            text = self._attraction_text(attraction)
            if "博物馆" in text:
                return "museum"
            if "纪念馆" in text:
                return "memorial"
            if any(token in text for token in ("古镇", "老街", "街区", "步行街")):
                return "historic_street"
            return "culture"
        if "family" in tags:
            return "family"
        return (attraction.category or "attraction").split(";")[0]

    @staticmethod
    def _attraction_text(attraction: Attraction) -> str:
        return " ".join(
            [
                attraction.name or "",
                attraction.address or "",
                attraction.category or "",
            ]
        )

    def _location_matches_city(self, location: Location, city: str) -> bool:
        center = CITY_CENTERS.get(
            city,
            CITY_CENTERS.get(city.removesuffix("市"), CITY_CENTERS.get(city.removesuffix("区"))),
        )
        if center is None:
            return True

        radius_km = 45.0 if city.endswith("区") else 120.0
        if city in {"重庆", "重庆市"}:
            radius_km = 180.0

        return self._distance_km(
            center[0],
            center[1],
            location.longitude,
            location.latitude,
        ) <= radius_km

    @staticmethod
    def _distance_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
        import math

        radius = 6371.0
        lat1_r = math.radians(lat1)
        lat2_r = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        h = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
        )
        return radius * 2 * math.asin(math.sqrt(h))

    def _attraction_from_payload(
        self,
        payload: dict[str, Any],
        keywords: list[str],
    ) -> Attraction | None:
        location = self._parse_location(payload.get("location"))
        if location is None:
            return None

        photos = payload.get("photos") if isinstance(payload.get("photos"), dict) else {}
        rating = self._parse_rating(payload.get("rating"))
        ticket_price = self._parse_ticket_price(payload.get("ticket_ordering"))
        category = str(payload.get("type") or "attraction").split(";")[0]

        return Attraction(
            name=str(payload.get("name") or "Unnamed attraction"),
            address=str(payload.get("address") or ""),
            location=location,
            visit_duration=120,
            description=(
                f"{category} in {payload.get('city') or 'the destination'}. "
                f"Matched keywords: {', '.join(keywords)}."
            ),
            category=category,
            rating=rating,
            image_url=photos.get("url") or None,
            ticket_price=ticket_price,
        )

    def _looks_like_attraction(self, payload: dict[str, Any]) -> bool:
        text = " ".join(
            str(payload.get(key) or "") for key in ("name", "type", "typecode", "address")
        )
        street_like = ("老街", "古镇", "历史街区", "步行街", "美食街", "夜市", "特色街区")
        restaurant_like = ("餐饮服务", "餐馆", "中餐厅", "火锅店", "小吃", "快餐", "咖啡厅")
        if any(item in text for item in street_like) and not any(
            item in text for item in restaurant_like
        ):
            return True
        blocked = (
            "餐饮服务", "购物服务", "体育休闲服务", "生活服务", "公司",
            "电子", "汽车", "住宿服务", "餐馆", "商场", "超市",
        )
        if any(item in text for item in blocked):
            return False
        allowed = (
            "风景名胜", "科教文化", "公园", "博物馆", "纪念馆",
            "旅游景点", "景区", "自然保护区", "国家级景点", "寺庙", "美术馆",
            "艺术馆", "历史建筑",
        )
        return any(item in text for item in allowed)

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

    def _parse_rating(self, value: Any) -> float | None:
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return None
        return max(0, min(rating, 5))

    def _parse_ticket_price(self, value: Any) -> int:
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    def _mock_attractions(
        self, request: TravelPlanRequest, keywords: list[str]
    ) -> list[Attraction]:
        city = request.city
        center_longitude, center_latitude = CITY_CENTERS.get(
            city,
            CITY_CENTERS.get(city.removesuffix("市"), CITY_CENTERS["北京"]),
        )
        base_data = [
            (
                f"{city}博物馆",
                f"{city}市中心文化区",
                "了解当地历史文化的必打卡地标。",
                "文化",
                60,
                120,
                0.0,
                0.0,
            ),
            (
                f"{city}城市公园",
                f"{city}滨水区",
                "休闲放松、拍照散步的绝佳去处。",
                "自然",
                20,
                90,
                0.012,
                0.008,
            ),
            (
                f"{city}老街",
                f"{city}老城区",
                "品尝当地小吃、感受市井烟火气的特色街道。",
                "文化",
                0,
                90,
                -0.014,
                0.006,
            ),
            (
                f"{city}观景台",
                f"{city}制高点",
                "俯瞰城市全景的绝佳视角点。",
                "地标",
                80,
                60,
                0.018,
                -0.01,
            ),
        ]

        return [
            Attraction(
                name=name,
                address=address,
                location=Location(
                    longitude=center_longitude + longitude_offset,
                    latitude=center_latitude + latitude_offset,
                ),
                visit_duration=duration,
                description=f"{description} Matched keywords: {', '.join(keywords)}.",
                category=category,
                rating=4.5 + index * 0.1,
                image_url=None,
                ticket_price=ticket_price,
            )
            for index, (
                name,
                address,
                description,
                category,
                ticket_price,
                duration,
                longitude_offset,
                latitude_offset,
            ) in enumerate(base_data)
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
        if detail_statuses:
            return f"MCP search status: {search_statuses}; detail status: {detail_statuses}."
        return f"MCP search status: {search_statuses}."


AttractionAgent = AttractionSearchAgent
