"""Geographic day grouping helpers for PlannerAgent."""

from __future__ import annotations

from app.models.travel import Attraction, Hotel, TravelPlanRequest
from app.utils.geo import geo_distance_km


class GeoDayPlanner:
    """Cluster attractions into day-sized geographic routes."""

    def cluster_attractions(
        self,
        attractions: list[Attraction],
        k: int,
    ) -> list[list[Attraction]]:
        if not attractions or k <= 0:
            return [[] for _ in range(k)]
        if k >= len(attractions):
            clusters = [[attraction] for attraction in attractions]
            clusters += [[] for _ in range(k - len(attractions))]
            return clusters

        sorted_attractions = sorted(
            attractions,
            key=lambda item: item.location.longitude + item.location.latitude,
        )
        step = len(sorted_attractions) / k
        centroids: list[tuple[float, float]] = [
            (
                sorted_attractions[int(i * step)].location.longitude,
                sorted_attractions[int(i * step)].location.latitude,
            )
            for i in range(k)
        ]

        clusters: list[list[Attraction]] = [[] for _ in range(k)]
        for _ in range(10):
            new_clusters: list[list[Attraction]] = [[] for _ in range(k)]
            for attraction in attractions:
                nearest = min(
                    range(k),
                    key=lambda index: (
                        (attraction.location.longitude - centroids[index][0]) ** 2
                        + (attraction.location.latitude - centroids[index][1]) ** 2
                    ),
                )
                new_clusters[nearest].append(attraction)

            changed = False
            for index, cluster in enumerate(new_clusters):
                if not cluster:
                    continue
                longitude = sum(item.location.longitude for item in cluster) / len(cluster)
                latitude = sum(item.location.latitude for item in cluster) / len(cluster)
                if (longitude, latitude) != centroids[index]:
                    centroids[index] = (longitude, latitude)
                    changed = True

            clusters = new_clusters
            if not changed:
                break

        for index, cluster in enumerate(clusters):
            if not cluster:
                largest = max(range(k), key=lambda item: len(clusters[item]))
                if len(clusters[largest]) > 1:
                    clusters[index] = [clusters[largest].pop()]

        order = sorted(
            range(k),
            key=lambda index: (
                sum(item.location.longitude for item in clusters[index])
                / max(len(clusters[index]), 1)
            ),
        )
        return [clusters[index] for index in order]

    @staticmethod
    def balance_day_clusters(
        clusters: list[list[Attraction]],
        max_per_day: int,
    ) -> list[list[Attraction]]:
        if max_per_day <= 0:
            return clusters

        changed = True
        while changed:
            changed = False
            oversized = [
                index for index, cluster in enumerate(clusters)
                if len(cluster) > max_per_day
            ]
            if not oversized:
                break

            for source_index in oversized:
                source = clusters[source_index]
                while len(source) > max_per_day:
                    target_index = min(
                        range(len(clusters)),
                        key=lambda index: (len(clusters[index]), index == source_index),
                    )
                    if target_index == source_index:
                        break
                    clusters[target_index].append(source.pop())
                    changed = True
        return clusters

    @staticmethod
    def max_attractions_per_day(
        request: TravelPlanRequest,
        attractions: list[Attraction],
    ) -> int:
        if request.transportation == "public transit + walking":
            return 2
        if any(attraction.visit_duration >= 150 for attraction in attractions):
            return 2
        return 3

    @staticmethod
    def order_route(
        attractions: list[Attraction],
        hotel: Hotel | None = None,
    ) -> list[Attraction]:
        if len(attractions) <= 1:
            return attractions

        remaining = attractions[:]
        ordered: list[Attraction] = []
        if hotel and hotel.location:
            first = min(
                remaining,
                key=lambda item: geo_distance_km(
                    hotel.location.longitude,
                    hotel.location.latitude,
                    item.location.longitude,
                    item.location.latitude,
                ),
            )
        else:
            first = min(
                remaining,
                key=lambda item: (item.location.longitude, item.location.latitude),
            )

        ordered.append(first)
        remaining.remove(first)
        while remaining:
            current = ordered[-1]
            next_item = min(
                remaining,
                key=lambda item: geo_distance_km(
                    current.location.longitude,
                    current.location.latitude,
                    item.location.longitude,
                    item.location.latitude,
                ),
            )
            ordered.append(next_item)
            remaining.remove(next_item)
        return ordered

    @staticmethod
    def day_description(
        request: TravelPlanRequest,
        attractions: list[Attraction],
        index: int,
    ) -> str:
        if not attractions:
            return f"第{index + 1}天：{request.city}轻松休整与周边探索"
        tags: set[str] = set()
        for attraction in attractions:
            text = " ".join([attraction.name, attraction.category or "", attraction.description])
            if any(token in text for token in ("夜景", "观景", "索道", "江", "山")):
                tags.add("山城夜景与立体交通")
            if any(token in text for token in ("古镇", "老街", "历史", "文化", "民俗")):
                tags.add("历史街区与城市文化")
            if any(token in text for token in ("公园", "自然", "山", "湿地")):
                tags.add("自然休闲与城市景观")
            if any(token in text for token in ("美食", "步行街", "街区")):
                tags.add("街区漫游与地方风味")
        theme = "、".join(list(tags)[:2]) or "精选景点串联"
        return f"第{index + 1}天：{theme}"

    @staticmethod
    def max_day_leg_km(attractions: list[Attraction]) -> float:
        if len(attractions) < 2:
            return 0.0
        max_leg = 0.0
        for first, second in zip(attractions, attractions[1:]):
            max_leg = max(
                max_leg,
                geo_distance_km(
                    first.location.longitude,
                    first.location.latitude,
                    second.location.longitude,
                    second.location.latitude,
                ),
            )
        return max_leg
