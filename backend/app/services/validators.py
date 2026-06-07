"""Post-planning validation and auto-fix utilities."""

from app.models.travel import TravelPlanRequest, TripPlan


def validate_trip_plan(
    plan: TripPlan,
    request: TravelPlanRequest,
) -> tuple[TripPlan, list[str]]:
    """
    Validate a TripPlan and fix obvious issues in-place.
    Returns (fixed_plan, warnings).
    """
    warnings: list[str] = []

    # ── 1. Remove duplicate attractions across all days ──────────────────
    seen: set[str] = set()
    for day in plan.days:
        deduped = []
        for att in day.attractions:
            if att.name not in seen:
                seen.add(att.name)
                deduped.append(att)
            else:
                warnings.append(f"景点「{att.name}」在行程中重复出现，已自动去重")
        day.attractions = deduped

    # ── 2. Warn about empty days ─────────────────────────────────────────
    for day in plan.days:
        if not day.attractions:
            warnings.append(
                f"第{day.day_index + 1}天（{day.date}）暂无景点安排，建议手动补充"
            )

    # ── 3. Budget overflow check ─────────────────────────────────────────
    if request.budget and plan.budget and plan.budget.total > 0:
        ratio = plan.budget.total / max(request.budget, 1)
        if ratio > 1.2:
            warnings.append(
                f"预计总费用 {plan.budget.total} 元较您的预算 {request.budget} 元"
                f"超出 {int((ratio - 1) * 100)}%，建议缩减行程或调整住宿标准"
            )

    return plan, warnings
