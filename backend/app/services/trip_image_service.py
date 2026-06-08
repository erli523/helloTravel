"""Trip image enrichment service."""

import asyncio
from urllib.parse import quote, urlparse

from app.models.travel import Attraction, TripPlan
from app.config import get_settings
from app.services.unsplash_service import UnsplashService


ALLOWED_IMAGE_HOSTS = {
    "images.unsplash.com",
    "plus.unsplash.com",
    "store.is.autonavi.com",
    "aos-cdn-image.amap.com",
    "aos-comment.amap.com",
}


class TripImageService:
    """Enriches attraction records with image URLs."""

    def __init__(self, unsplash_service: UnsplashService | None = None) -> None:
        self.unsplash_service = unsplash_service or UnsplashService()
        self.settings = get_settings()

    async def enrich_attraction_images(self, trip_plan: TripPlan) -> TripPlan:
        """Fill browser-safe attraction image URLs using Unsplash."""

        if not self.unsplash_service.available:
            self._remove_unsafe_image_urls(trip_plan)
            return trip_plan

        image_tasks: list[tuple[Attraction, str]] = []
        for day in trip_plan.days:
            for attraction in day.attractions:
                if attraction.image_url and attraction.image_url.startswith("/api/"):
                    continue
                existing_image = self._proxy_url(attraction.image_url)
                if existing_image:
                    attraction.image_url = existing_image
                    continue

                image_tasks.append((attraction, f"{attraction.name} {trip_plan.city}"))

        image_task = asyncio.create_task(self._enrich_from_unsplash(image_tasks))
        _, pending = await asyncio.wait(
            {image_task},
            timeout=self.settings.image_enrich_timeout,
        )
        if pending:
            image_task.cancel()
            for attraction, _ in image_tasks:
                attraction.image_url = self._safe_existing_url(attraction.image_url)
        return trip_plan

    def status(self) -> dict:
        return self.unsplash_service.status()

    def _remove_unsafe_image_urls(self, trip_plan: TripPlan) -> None:
        for day in trip_plan.days:
            for attraction in day.attractions:
                attraction.image_url = self._safe_existing_url(attraction.image_url)

    def _safe_existing_url(self, url: str | None) -> str | None:
        if not url:
            return None
        if url.startswith("/api/"):
            return url
        return self._proxy_url(url)

    def _proxy_url(self, url: str | None) -> str | None:
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        if parsed.netloc.lower() not in ALLOWED_IMAGE_HOSTS:
            return None
        return f"/api/travel/images/proxy?url={quote(url, safe='')}"

    async def _enrich_from_unsplash(
        self,
        image_tasks: list[tuple[Attraction, str]],
    ) -> None:
        semaphore = asyncio.Semaphore(4)

        async def fill_image(attraction: Attraction, query: str) -> None:
            async with semaphore:
                source_url = await self.unsplash_service.get_photo_url(query)
                attraction.image_url = self._proxy_url(source_url)

        await asyncio.gather(
            *(fill_image(attraction, query) for attraction, query in image_tasks)
        )
