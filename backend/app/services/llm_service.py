"""LLM API adapter."""

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
                        "Return a concise user-visible response for this Agent. "
                        "Do not reveal hidden chain-of-thought. Summarize decisions, "
                        "tool usage, and key results in 2-4 short Chinese sentences."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Agent: {agent_name}\n"
                        f"User query: {user_query}\n\n"
                        f"Available context:\n{context}"
                    ),
                },
            ],
            "temperature": 0.3,
            "max_tokens": 320,
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
            logger.warning("LLM response failed for {}: {}", agent_name, exc)
            return fallback

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return fallback
        return str(content).strip() or fallback
