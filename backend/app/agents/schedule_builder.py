"""Timeline construction and repair helpers for itinerary planning."""

from __future__ import annotations

from typing import Any

from app.models.travel import Attraction, DayPlan, Meal, ScheduleItem, TravelPlanRequest
from app.utils.geo import geo_distance_km


class ScheduleBuilder:
    """Build and repair day timelines without depending on Agent state."""

    @staticmethod
    def fmt_time(minutes: int) -> str:
        h = (minutes // 60) % 24
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    @staticmethod
    def parse_time_minutes(value: str) -> int | None:
        try:
            hour, minute = value.split(":", 1)
            return int(hour) * 60 + int(minute)
        except (AttributeError, ValueError):
            return None

    @staticmethod
    def parse_llm_schedule(raw: list[Any]) -> list[ScheduleItem]:
        result: list[ScheduleItem] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                result.append(
                    ScheduleItem(
                        time=str(item.get("time") or ""),
                        end_time=str(item.get("end_time") or ""),
                        activity=str(item.get("activity") or ""),
                        location=str(item.get("location") or ""),
                        notes=str(item.get("notes") or ""),
                        item_type=str(
                            item.get("item_type") or item.get("type") or "attraction"
                        ),
                    )
                )
            except Exception:
                continue
        return result

    @classmethod
    def normalize_schedule(cls, schedule: list[ScheduleItem]) -> list[ScheduleItem]:
        cleaned: list[ScheduleItem] = []
        for item in sorted(schedule, key=lambda entry: cls.parse_time_minutes(entry.time) or 0):
            start = cls.parse_time_minutes(item.time)
            end = cls.parse_time_minutes(item.end_time)
            if start is None or end is None:
                continue
            if start >= 20 * 60 or end <= start:
                continue
            if end > 20 * 60:
                item = item.model_copy(update={"end_time": "20:00"})
            cleaned.append(item)
        return cleaned

    @classmethod
    def fill_schedule_gaps(cls, schedule: list[ScheduleItem]) -> list[ScheduleItem]:
        schedule = cls.normalize_schedule(schedule)
        if len(schedule) < 2:
            return schedule

        filled: list[ScheduleItem] = []
        for index, item in enumerate(schedule):
            filled.append(item)
            if index >= len(schedule) - 1:
                continue

            end = cls.parse_time_minutes(item.end_time)
            next_start = cls.parse_time_minutes(schedule[index + 1].time)
            if end is None or next_start is None:
                continue

            gap = next_start - end
            if gap < 20:
                continue

            item_type = "rest" if gap < 120 else "free"
            activity = "周边慢游与短暂休整" if gap < 120 else "周边街区慢游 / 返回酒店整备"
            notes = (
                "避免两个正式项目之间空等，可在上一站附近补充休息、拍照或短距离闲逛。"
                if gap < 120
                else "该空档较长，建议安排返回酒店整理、午休，或选择上一站附近的轻量街区活动。"
            )
            filled.append(
                ScheduleItem(
                    time=item.end_time,
                    end_time=schedule[index + 1].time,
                    activity=activity,
                    location=item.location,
                    notes=notes,
                    item_type=item_type,
                )
            )
        return cls.normalize_schedule(filled)

    @classmethod
    def build_default_schedule(
        cls,
        request: TravelPlanRequest,
        attractions: list[Attraction],
        meals: list[Meal],
    ) -> list[ScheduleItem]:
        schedule: list[ScheduleItem] = []
        current = 10 * 60

        breakfast = next((m for m in meals if m.type == "breakfast"), None)
        lunch = next((m for m in meals if m.type == "lunch"), None)
        dinner = next((m for m in meals if m.type == "dinner"), None)

        if breakfast:
            schedule.append(
                ScheduleItem(
                    time="08:30",
                    end_time="09:30",
                    activity=f"早餐：{breakfast.name}",
                    location="酒店",
                    notes="在酒店享用早餐，为一天游览储备能量。",
                    item_type="meal",
                )
            )

        schedule.append(
            ScheduleItem(
                time="09:30",
                end_time="10:00",
                activity="整理行装，出发前往景区",
                location="",
                notes="确认景点开放时间及预约情况，规划当天最优路线。",
                item_type="transit",
            )
        )

        lunch_inserted = False
        evening_attractions = [att for att in attractions if cls.is_evening_attraction(att)]
        daytime_attractions = [att for att in attractions if att not in evening_attractions]

        for index, attraction in enumerate(daytime_attractions):
            if not lunch_inserted and current >= 12 * 60:
                current = cls._append_lunch(schedule, request, lunch, current)
                lunch_inserted = True

            if current + attraction.visit_duration > 18 * 60:
                if not lunch_inserted:
                    current = cls._append_lunch(schedule, request, lunch, max(current, 12 * 60))
                    lunch_inserted = True
                remaining = [item.name for item in daytime_attractions[index : index + 2]]
                schedule.append(
                    ScheduleItem(
                        time=cls.fmt_time(max(current, 16 * 60)),
                        end_time="18:00",
                        activity="自由活动 / 特色街区闲逛",
                        location="",
                        notes=(
                            "今日行程较为充实，可在附近特色街区放松游逛。"
                            + (
                                f" {'、'.join(remaining)} 等景点建议安排至其他天。"
                                if remaining
                                else ""
                            )
                        ),
                        item_type="rest",
                    )
                )
                break

            schedule.append(
                ScheduleItem(
                    time=cls.fmt_time(current),
                    end_time=cls.fmt_time(current + attraction.visit_duration),
                    activity=f"游览：{attraction.name}",
                    location=attraction.name,
                    notes=cls._attraction_notes(attraction),
                    item_type="attraction",
                )
            )
            current += attraction.visit_duration

            if index < len(daytime_attractions) - 1:
                next_attraction = daytime_attractions[index + 1]
                transit_min, transit_note = cls._transit_estimate(attraction, next_attraction)
                if current + transit_min < 18 * 60:
                    schedule.append(
                        ScheduleItem(
                            time=cls.fmt_time(current),
                            end_time=cls.fmt_time(current + transit_min),
                            activity=f"前往{next_attraction.name}",
                            location="",
                            notes=transit_note,
                            item_type="transit",
                        )
                    )
                    current += transit_min

        if not lunch_inserted:
            lunch_start = max(current, 12 * 60)
            if lunch_start + 90 <= 20 * 60:
                current = cls._append_lunch(schedule, request, lunch, lunch_start)

        dinner_start = max(current, 17 * 60 + 30 if evening_attractions else 18 * 60)
        if dinner_start < 20 * 60:
            dinner_end = min(dinner_start + (60 if evening_attractions else 90), 20 * 60)
            schedule.append(
                ScheduleItem(
                    time=cls.fmt_time(dinner_start),
                    end_time=cls.fmt_time(dinner_end),
                    activity=f"晚餐：{dinner.name if dinner else request.city + '招牌晚餐'}",
                    location=(dinner.address or "") if dinner else "",
                    notes="品尝当地招牌美食，结束一天的精彩行程。",
                    item_type="meal",
                )
            )
            current = dinner_end

        for attraction in evening_attractions:
            start = max(current, 18 * 60 + 30)
            duration = min(max(60, attraction.visit_duration), 90)
            if start + duration > 20 * 60:
                duration = 20 * 60 - start
            if duration < 30:
                continue
            schedule.append(
                ScheduleItem(
                    time=cls.fmt_time(start),
                    end_time=cls.fmt_time(start + duration),
                    activity=f"夜间游览：{attraction.name}",
                    location=attraction.name,
                    notes="该景点更适合傍晚或夜间观赏，建议结合灯光、江景或城市夜景安排。",
                    item_type="attraction",
                )
            )
            current = start + duration

        return cls.fill_schedule_gaps(schedule)

    @staticmethod
    def is_evening_attraction(attraction: Attraction) -> bool:
        text = " ".join(
            [
                attraction.name or "",
                attraction.category or "",
                attraction.description or "",
            ]
        )
        return any(
            token in text
            for token in ("夜景", "夜游", "灯光", "观景台", "洪崖洞", "一棵树", "南山")
        )

    @classmethod
    def repair_and_validate_days(
        cls,
        request: TravelPlanRequest,
        days: list[DayPlan],
        max_day_leg_km: Any,
    ) -> tuple[list[DayPlan], list[str]]:
        repaired_days: list[DayPlan] = []
        notes: list[str] = []
        for day in days:
            timeline, day_notes = cls.repair_timeline(day.timeline)
            if day_notes:
                notes.append(f"第 {day.day_index + 1} 天已修正时间轴问题")

            if len(day.attractions) > 3 and request.transportation == "public transit + walking":
                notes.append(f"第 {day.day_index + 1} 天公共交通景点偏多，建议现场保留弹性")

            meal_types = {meal.type for meal in day.meals}
            if "lunch" not in meal_types:
                notes.append(f"第 {day.day_index + 1} 天缺少明确午餐安排")
            if "dinner" not in meal_types:
                notes.append(f"第 {day.day_index + 1} 天缺少明确晚餐安排")

            max_leg = max_day_leg_km(day.attractions)
            if max_leg > 18 and request.transportation == "public transit + walking":
                notes.append(f"第 {day.day_index + 1} 天存在 {max_leg:.0f} 公里以上跨区移动")

            repaired_days.append(day.model_copy(update={"timeline": timeline}))

        return repaired_days, list(dict.fromkeys(notes))

    @classmethod
    def repair_timeline(
        cls,
        timeline: list[ScheduleItem],
    ) -> tuple[list[ScheduleItem], list[str]]:
        normalized = cls.normalize_schedule(timeline)
        if not normalized:
            return [], ["empty timeline"]

        repaired: list[ScheduleItem] = []
        notes: list[str] = []
        cursor = 8 * 60 + 30
        for item in normalized:
            start = cls.parse_time_minutes(item.time)
            end = cls.parse_time_minutes(item.end_time)
            if start is None or end is None:
                notes.append("invalid time")
                continue

            duration = end - start
            if start < cursor:
                if item.item_type in {"transit", "rest", "free"} and end <= cursor + 5:
                    notes.append("dropped overlap")
                    continue
                start = cursor
                end = min(start + duration, 20 * 60)
                if end <= start:
                    notes.append("dropped overlap")
                    continue
                item = item.model_copy(
                    update={
                        "time": cls.fmt_time(start),
                        "end_time": cls.fmt_time(end),
                    }
                )
                notes.append("shifted overlap")

            repaired.append(item)
            cursor = cls.parse_time_minutes(item.end_time) or end

        return cls.fill_schedule_gaps(repaired), notes

    @classmethod
    def _append_lunch(
        cls,
        schedule: list[ScheduleItem],
        request: TravelPlanRequest,
        lunch: Meal | None,
        start: int,
    ) -> int:
        end = start + 90
        schedule.append(
            ScheduleItem(
                time=cls.fmt_time(start),
                end_time=cls.fmt_time(end),
                activity=f"午餐：{lunch.name if lunch else request.city + '特色午餐'}",
                location=(lunch.address or "") if lunch else "",
                notes="就近选择特色餐厅，享用午餐后稍作休息。",
                item_type="meal",
            )
        )
        return end

    @staticmethod
    def _attraction_notes(attraction: Attraction) -> str:
        return (
            f"建议游览约 {attraction.visit_duration} 分钟"
            + (
                f"，门票 {attraction.ticket_price} 元/人"
                if attraction.ticket_price > 0
                else "，免费开放"
            )
            + (f"，综合评分 {attraction.rating} 分" if attraction.rating else "")
            + "。"
        )

    @staticmethod
    def _transit_estimate(
        attraction: Attraction,
        next_attraction: Attraction,
    ) -> tuple[int, str]:
        distance = geo_distance_km(
            attraction.location.longitude,
            attraction.location.latitude,
            next_attraction.location.longitude,
            next_attraction.location.latitude,
        )
        if distance < 1:
            return 10, "步行约 10 分钟可达。"
        if distance < 4:
            return 20, "步行或骑行约 20 分钟可达。"
        if distance < 12:
            return 35, "乘坐公交 / 地铁约 30-40 分钟可达。"
        return 50, "乘坐地铁约 40-50 分钟可达。"
