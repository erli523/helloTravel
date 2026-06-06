"""Unsplash image API adapter."""

from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from app.config import Settings, get_settings


class UnsplashPhoto(BaseModel):
    """Normalized photo metadata returned by Unsplash."""

    url: str = Field(..., description="Regular image URL")
    description: str = Field(default="", description="Photo description")
    photographer: str = Field(default="", description="Photographer name")


class UnsplashService:
    """Searches Unsplash photos for attractions."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def available(self) -> bool:
        return bool(self.settings.unsplash_enabled and self.settings.unsplash_api_key)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.unsplash_enabled,
            "available": self.available,
            "base_url": self.settings.unsplash_base_url,
            "reason": None
            if self.available
            else "UNSPLASH_ACCESS_KEY is not configured or service is disabled.",
        }

    async def search_photos(
        self,
        query: str,
        per_page: int | None = None,
    ) -> list[UnsplashPhoto]:
        """Search photos by query and return normalized metadata."""

        if not self.available:
            return []

        params = {
            "query": query,
            "per_page": per_page or self.settings.unsplash_per_page,
            "client_id": self.settings.unsplash_api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.unsplash_timeout) as client:
                response = await client.get(
                    f"{self.settings.unsplash_base_url}/search/photos",
                    params=params,
                )
                response.raise_for_status()
        except Exception as exc:
            logger.warning("Unsplash photo search failed for {!r}: {}", query, exc)
            return []

        results = response.json().get("results", [])
        photos: list[UnsplashPhoto] = []
        for item in results:
            urls = item.get("urls") or {}
            regular_url = urls.get("regular")
            if not regular_url:
                continue
            user = item.get("user") or {}
            photos.append(
                UnsplashPhoto(
                    url=regular_url,
                    description=item.get("description")
                    or item.get("alt_description")
                    or "",
                    photographer=user.get("name") or "",
                )
            )
        return photos

    async def get_photo_url(self, query: str) -> str | None:
        """Return the first image URL for a query."""

        photos = await self.search_photos(query, per_page=1)
        return photos[0].url if photos else None
