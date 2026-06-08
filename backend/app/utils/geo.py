"""Shared geographic helpers for travel planning agents."""

from __future__ import annotations

import math
from typing import Protocol, TypeVar


class HasLocation(Protocol):
    location: object


T = TypeVar("T", bound=HasLocation)


def geo_distance_km(
    lng1: float,
    lat1: float,
    lng2: float,
    lat2: float,
) -> float:
    """Approximate great-circle distance in kilometers."""

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


def location_centroid(items: list[T]) -> tuple[float, float] | None:
    """Return longitude/latitude centroid for model objects with a location."""

    if not items:
        return None
    return (
        sum(getattr(item.location, "longitude") for item in items) / len(items),
        sum(getattr(item.location, "latitude") for item in items) / len(items),
    )
