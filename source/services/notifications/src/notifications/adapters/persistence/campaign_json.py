"""Преобразование доменных значений кампании в JSONB и обратно."""

from datetime import datetime
from typing import Any

from notifications.domain import DebtorSelection, ScheduleKind, ScheduleSpec


def selection_to_json(selection: DebtorSelection) -> dict[str, Any]:
    """Записать критерии выборки в JSONB."""
    return {"criteria": dict(selection.criteria)}


def selection_from_json(value: dict[str, Any]) -> DebtorSelection:
    """Прочитать критерии выборки из JSONB."""
    criteria = value.get("criteria", {})
    if not isinstance(criteria, dict):
        return DebtorSelection(criteria={})
    return DebtorSelection(criteria={str(key): str(item) for key, item in criteria.items()})


def schedule_to_json(schedule: ScheduleSpec | None) -> dict[str, Any] | None:
    """Записать правило запуска в JSONB."""
    if schedule is None:
        return None
    return {
        "kind": schedule.kind.value,
        "timezone": schedule.timezone,
        "run_at": schedule.run_at.isoformat() if schedule.run_at is not None else None,
        "cron": schedule.cron,
    }


def schedule_from_json(value: dict[str, Any] | None) -> ScheduleSpec | None:
    """Прочитать правило запуска из JSONB."""
    if value is None:
        return None
    run_at_value = value.get("run_at")
    run_at = datetime.fromisoformat(str(run_at_value)) if run_at_value else None
    cron_value = value.get("cron")
    return ScheduleSpec(
        kind=ScheduleKind(str(value.get("kind", ScheduleKind.ONE_OFF.value))),
        timezone=str(value.get("timezone", "UTC")),
        run_at=run_at,
        cron=str(cron_value) if cron_value is not None else None,
    )
