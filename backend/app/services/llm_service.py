"""LLM API adapter."""

import json
import re
from typing import Any

import httpx
from loguru import logger

from app.config import Settings, get_settings


class LLMService:
    """OpenAI-compatible adapter for role Agent responses."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def available(self) -> bool:
        return bool(self.settings.llm_enabled and self.settings.llm_api_key)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.llm_enabled,
            "available": self.available,
            "model": self.settings.llm_model_id,
            "base_url": self.settings.llm_base_url,
        }

    # ── Short agent summary (called per specialist agent) ────────────────

    async def generate_agent_reply(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        user_query: str,
        context: str,
        fallback: str,
    ) -> str:
        """Generate a concise role response; fall back safely on errors."""

        if not self.available:
            return fallback

        payload = {
            "model": self.settings.llm_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt}\n\n"
                        "请为该 Agent 生成一段简洁的、面向用户的中文回复。"
                        "不要暴露内部推理过程，用2-4句话概括决策依据、工具调用情况和关键结果。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Agent：{agent_name}\n"
                        f"用户需求：{user_query}\n\n"
                        f"可用上下文：\n{context}"
                    ),
                },
            ],
            "temperature": 0.3,
            "max_tokens": 320,
        }
        return await self._chat(payload, fallback=fallback, label=agent_name)

    # ── Full itinerary planning (called once by PlannerAgent) ────────────

    async def assign_itinerary_days(
        self,
        *,
        system_prompt: str,
        planning_context: str,
    ) -> dict[str, Any] | None:
        """Ask the LLM only for attraction/meal/hotel assignment."""

        if not self.available:
            return None

        payload = {
            "model": self.settings.llm_model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": planning_context},
            ],
            "temperature": 0.3,
            "max_tokens": 1500,
        }
        content = await self._chat(
            payload,
            fallback="",
            label="PlannerAgent.assign_itinerary_days",
        )
        if not content:
            return None
        return self._parse_json_response(content)

    async def generate_day_schedule(
        self,
        *,
        day_context: str,
    ) -> list[dict[str, Any]] | None:
        """Ask the LLM for one day's timeline only."""

        if not self.available:
            return None

        payload = {
            "model": self.settings.llm_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是中文旅行日程规划专家。只返回 JSON 数组，不要输出解释文字。"
                        "每一项必须包含 time、end_time、activity、location、notes、item_type。"
                        "item_type 只能是 attraction、meal、transit、rest。"
                        "所有 activity 和 notes 使用中文，时间控制在 08:30 到 20:00 之间。"
                    ),
                },
                {"role": "user", "content": day_context},
            ],
            "temperature": 0.35,
            "max_tokens": 900,
        }
        content = await self._chat(
            payload,
            fallback="",
            label="PlannerAgent.generate_day_schedule",
        )
        if not content:
            return None
        parsed = self._parse_json_any_response(content)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict) and isinstance(parsed.get("schedule"), list):
            return [item for item in parsed["schedule"] if isinstance(item, dict)]
        return None

    async def select_attraction_keywords(
        self,
        *,
        city: str,
        preferences: list[str],
        fallback_keywords: list[str],
    ) -> list[str] | None:
        """Ask AttractionSearchAgent for diverse Amap POI search intents."""

        if not self.available:
            return None

        payload = {
            "model": self.settings.llm_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are AttractionSearchAgent. Return only JSON with a "
                        "keywords array. Generate 5-8 short Amap POI search keywords "
                        "for the destination city. Treat multiple preferences as OR "
                        "intent coverage, not as one combined AND query. Prefer city-"
                        "specific streets, scenic areas, cultural sites, viewpoints, "
                        "and food districts. Do not include restaurant names."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "city": city,
                            "preferences": preferences,
                            "fallback_keywords": fallback_keywords,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.35,
            "max_tokens": 420,
        }
        content = await self._chat(
            payload,
            fallback="",
            label="AttractionSearchAgent.select_keywords",
        )
        if not content:
            return None
        parsed = self._parse_json_any_response(content)
        if isinstance(parsed, dict):
            keywords = parsed.get("keywords")
        elif isinstance(parsed, list):
            keywords = parsed
        else:
            keywords = None
        if not isinstance(keywords, list):
            return None
        clean_keywords = [
            str(keyword).strip()
            for keyword in keywords
            if str(keyword).strip()
        ]
        return list(dict.fromkeys(clean_keywords))[:8] or None

    async def rank_attraction_candidates(
        self,
        *,
        city: str,
        preferences: list[str],
        candidates: list[dict[str, Any]],
        target_count: int,
    ) -> list[str] | None:
        """Ask AttractionSearchAgent to rank real POI candidates by fit and variety."""

        if not self.available or not candidates:
            return None

        payload = {
            "model": self.settings.llm_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are AttractionSearchAgent. Return only JSON with a "
                        "ranked_names array. Rank the provided real POI candidates "
                        "for a travel itinerary. Prefer authentic local variety and "
                        "cover selected preferences as OR intents. Avoid choosing only "
                        "museums for culture; mix historic streets, landmarks, nature, "
                        "viewpoints, and food streets when available. Only use names "
                        "from the provided candidates."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "city": city,
                            "preferences": preferences,
                            "target_count": target_count,
                            "candidates": candidates[:24],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.25,
            "max_tokens": 700,
        }
        content = await self._chat(
            payload,
            fallback="",
            label="AttractionSearchAgent.rank_candidates",
        )
        if not content:
            return None
        parsed = self._parse_json_any_response(content)
        if isinstance(parsed, dict):
            names = parsed.get("ranked_names") or parsed.get("names")
        elif isinstance(parsed, list):
            names = parsed
        else:
            names = None
        if not isinstance(names, list):
            return None
        clean_names = [str(name).strip() for name in names if str(name).strip()]
        return list(dict.fromkeys(clean_names)) or None

    async def choose_react_action(
        self,
        *,
        issues: list[dict[str, Any]],
        available_actions: list[str],
        executed_actions: list[str],
    ) -> str | None:
        """Let PlannerAgent's ReAct loop choose the next repair action."""

        if not self.available or not issues or not available_actions:
            return None

        payload = {
            "model": self.settings.llm_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are PlannerAgent's ReAct controller. Choose exactly one "
                        "next action from available_actions, or return null. Return "
                        "only JSON: {\"action\":\"...\",\"reason\":\"...\"}. "
                        "Prioritize actions that reduce user-visible itinerary defects."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "issues": issues[:12],
                            "available_actions": available_actions,
                            "executed_actions": executed_actions,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 160,
        }
        content = await self._chat(
            payload,
            fallback="",
            label="PlannerAgent.choose_react_action",
        )
        if not content:
            return None
        parsed = self._parse_json_any_response(content)
        if isinstance(parsed, dict):
            action = str(parsed.get("action") or "").strip()
        else:
            action = str(content).strip().strip('"')
        return action if action in available_actions else None

    async def select_food_keywords(
        self,
        *,
        city: str,
        preferences: list[str],
        fallback_keywords: list[str],
    ) -> list[str] | None:
        """Ask FoodRecommendationAgent for city-specific food search keywords."""

        if not self.available:
            return None

        payload = {
            "model": self.settings.llm_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are FoodRecommendationAgent. Return only JSON with a "
                        "keywords array. Generate 4-6 short Amap POI keywords for "
                        "local restaurants, snack shops, food streets, or signature "
                        "dishes in the city. Avoid retail, entertainment, and generic "
                        "tourist attractions."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "city": city,
                            "preferences": preferences,
                            "fallback_keywords": fallback_keywords,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.35,
            "max_tokens": 360,
        }
        content = await self._chat(
            payload,
            fallback="",
            label="FoodRecommendationAgent.select_keywords",
        )
        if not content:
            return None
        parsed = self._parse_json_any_response(content)
        keywords = parsed.get("keywords") if isinstance(parsed, dict) else parsed
        if not isinstance(keywords, list):
            return None
        clean = [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
        return list(dict.fromkeys(clean))[:6] or None

    async def select_best_hotel(
        self,
        *,
        candidates: list[dict[str, Any]],
        request_context: dict[str, Any],
    ) -> dict[str, str] | None:
        """Ask HotelAgent to select the most suitable hotel candidate."""

        if not self.available or not candidates:
            return None

        payload = {
            "model": self.settings.llm_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are HotelAgent. Return only JSON with hotel_name and "
                        "reason. Choose one exact hotel_name from candidates. Balance "
                        "budget level, accommodation preference, rating, location, "
                        "and suitability for the listed attraction area."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request": request_context,
                            "candidates": candidates[:12],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.2,
            "max_tokens": 260,
        }
        content = await self._chat(
            payload,
            fallback="",
            label="HotelAgent.select_best_hotel",
        )
        if not content:
            return None
        parsed = self._parse_json_any_response(content)
        if not isinstance(parsed, dict):
            return None
        hotel_name = str(parsed.get("hotel_name") or "").strip()
        if not hotel_name:
            return None
        return {
            "hotel_name": hotel_name,
            "reason": str(parsed.get("reason") or "").strip(),
        }

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _chat(
        self,
        payload: dict[str, Any],
        *,
        fallback: str,
        label: str = "unknown",
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
        except Exception as exc:
            logger.warning("LLM call failed for {}: {}", label, exc)
            return fallback

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return fallback
        return str(content).strip() or fallback

    def _parse_json_response(self, content: str) -> dict[str, Any] | None:
        """Extract and parse the first JSON object from an LLM response."""

        # Try direct parse
        try:
            result = json.loads(content.strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Strip markdown code fences (```json ... ```)
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # Extract the first JSON object found anywhere in the response
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(0))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        logger.warning(
            "Could not parse JSON from LLM response (first 300 chars): {}",
            content[:300],
        )
        return None

    def _parse_json_any_response(self, content: str) -> Any | None:
        """Extract and parse a JSON object or array from an LLM response."""

        stripped = content.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        fence = re.search(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", content, re.DOTALL)
        if fence:
            try:
                return json.loads(fence.group(1))
            except json.JSONDecodeError:
                pass

        start_candidates = [pos for pos in (content.find("{"), content.find("[")) if pos >= 0]
        if not start_candidates:
            return None
        start = min(start_candidates)
        opener = content[start]
        closer = "}" if opener == "{" else "]"
        end = content.rfind(closer)
        if end <= start:
            return None
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            logger.warning(
                "Could not parse JSON from LLM response (first 300 chars): {}",
                content[:300],
            )
            return None
