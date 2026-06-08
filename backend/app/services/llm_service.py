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

    async def generate_itinerary(
        self,
        *,
        system_prompt: str,
        planning_context: str,
    ) -> dict[str, Any] | None:
        """
        Ask LLM to produce a structured day-by-day itinerary.
        Returns a parsed dict on success, or None on failure.
        """
        if not self.available:
            return None

        payload = {
            "model": self.settings.llm_model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": planning_context},
            ],
            "temperature": 0.4,
            "max_tokens": 4000,
        }
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
            logger.warning("LLM itinerary generation failed: {}", exc)
            return None

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

        return self._parse_json_response(str(content))

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
                        "You are a travel schedule planner. Return only a JSON array. "
                        "Each item must include time, end_time, activity, location, "
                        "notes, and item_type. item_type must be one of attraction, "
                        "meal, transit, rest. Keep the day between 08:30 and 20:00."
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
