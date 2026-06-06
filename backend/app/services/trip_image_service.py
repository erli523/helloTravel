"""Trip image enrichment service."""

from app.models.travel import TripPlan
from app.services.unsplash_service import UnsplashService


class TripImageService:
    """Enriches attraction records with image URLs."""

    def __init__(self, unsplash_service: UnsplashService | None = None) -> None:
        self.unsplash_service = unsplash_service or UnsplashService()

    async def enrich_attraction_images(self, trip_plan: TripPlan) -> TripPlan:
        """Fill missing attraction image URLs using Unsplash."""

        if not self.unsplash_service.available:
            return trip_plan

        for day in trip_plan.days:
            for attraction in day.attractions:
                if attraction.image_url:
                    continue
                query = f"{attraction.name} {trip_plan.city}"
                attraction.image_url = await self.unsplash_service.get_photo_url(query)
        return trip_plan

    def status(self) -> dict:
        return self.unsplash_service.status()
