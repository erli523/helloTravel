"""Trip image enrichment service."""

from urllib.parse import quote, urlparse

from app.models.travel import TripPlan
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

    async def enrich_attraction_images(self, trip_plan: TripPlan) -> TripPlan:
        """Fill browser-safe attraction image URLs using Unsplash."""

        if not self.unsplash_service.available:
            self._remove_unsafe_image_urls(trip_plan)
            return trip_plan

        for day in trip_plan.days:
            for attraction in day.attractions:
                if attraction.image_url and attraction.image_url.startswith("/api/"):
                    continue
                existing_image = self._proxy_url(attraction.image_url)
                if existing_image:
                    attraction.image_url = existing_image
                    continue

                query = f"{attraction.name} {trip_plan.city}"
                source_url = await self.unsplash_service.get_photo_url(query)
                attraction.image_url = self._proxy_url(source_url)
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
