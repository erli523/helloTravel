"""Hotel selection helper consumed by PlannerAgent."""

from __future__ import annotations

from app.models.travel import Attraction, Hotel


class HotelSelector:
    """Select the hotel preferred by HotelAgent, with a deterministic fallback."""

    @staticmethod
    def select_best_hotel(
        hotels: list[Hotel],
        attractions: list[Attraction],
        preferred_name: str | None = None,
    ) -> Hotel | None:
        if not hotels:
            return None

        preferred_hotel = HotelSelector.find_hotel(preferred_name, hotels)
        if preferred_hotel is not None:
            return preferred_hotel

        if not attractions:
            return max(hotels, key=HotelSelector.hotel_rating_float)

        longitude = sum(item.location.longitude for item in attractions) / len(attractions)
        latitude = sum(item.location.latitude for item in attractions) / len(attractions)

        def score(hotel: Hotel) -> float:
            rating_score = HotelSelector.hotel_rating_float(hotel) / 5.0
            if hotel.location is not None:
                distance = (
                    (hotel.location.longitude - longitude) ** 2
                    + (hotel.location.latitude - latitude) ** 2
                ) ** 0.5
                proximity = max(0.0, 1.0 - distance / 0.15)
            else:
                proximity = 0.3
            return rating_score * 0.4 + proximity * 0.6

        return max(hotels, key=score)

    @staticmethod
    def hotel_rating_float(hotel: Hotel) -> float:
        try:
            return float(hotel.rating)
        except (TypeError, ValueError):
            return 3.5

    @staticmethod
    def find_hotel(name: str | None, hotels: list[Hotel]) -> Hotel | None:
        if not name:
            return None
        for hotel in hotels:
            if hotel.name == name:
                return hotel
        for hotel in hotels:
            if name in hotel.name or hotel.name in name:
                return hotel
        return None
