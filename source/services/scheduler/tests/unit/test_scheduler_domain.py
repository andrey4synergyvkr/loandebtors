"""Проверка доменных правил расписания Scheduler."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from scheduler.domain import (
    CampaignId,
    CampaignSchedule,
    ScheduleKind,
    ScheduleSpec,
    ScheduleStatus,
    ValidationError,
)

CAMPAIGN_ID = CampaignId(UUID("3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"))
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _one_off(run_at: datetime = NOW + timedelta(hours=1)) -> ScheduleSpec:
    """Вернуть разовое расписание."""
    return ScheduleSpec(kind=ScheduleKind.ONE_OFF, timezone="Europe/Moscow", run_at=run_at)


def _cron(expression: str = "0 10 * * 1-5") -> ScheduleSpec:
    """Вернуть cron-расписание."""
    return ScheduleSpec(kind=ScheduleKind.CRON, timezone="Europe/Moscow", cron=expression)


def test_one_off_spec_is_valid() -> None:
    """Разовое расписание содержит run_at и не содержит cron."""
    spec = _one_off()

    assert spec.kind is ScheduleKind.ONE_OFF
    assert spec.run_at is not None
    assert spec.cron is None


def test_cron_spec_is_valid() -> None:
    """Cron-расписание содержит выражение и не содержит run_at."""
    spec = _cron()

    assert spec.kind is ScheduleKind.CRON
    assert spec.cron == "0 10 * * 1-5"


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": ScheduleKind.ONE_OFF, "timezone": "Europe/Moscow"},
        {
            "kind": ScheduleKind.ONE_OFF,
            "timezone": "Europe/Moscow",
            "run_at": NOW,
            "cron": "0 10 * * *",
        },
        {
            "kind": ScheduleKind.ONE_OFF,
            "timezone": "Europe/Moscow",
            "run_at": datetime(2026, 1, 1),
        },
        {"kind": ScheduleKind.CRON, "timezone": "Europe/Moscow"},
        {
            "kind": ScheduleKind.CRON,
            "timezone": "Europe/Moscow",
            "cron": "",
            "run_at": NOW,
        },
        {"kind": ScheduleKind.CRON, "timezone": "Europe/Moscow", "cron": "0 10 * *"},
        {"kind": ScheduleKind.CRON, "timezone": "Unknown/Zone", "cron": "0 10 * * *"},
    ],
)
def test_invalid_spec_is_rejected(fields: dict[str, object]) -> None:
    """Противоречивые и неполные расписания отклоняются."""
    with pytest.raises(ValidationError):
        ScheduleSpec(**fields)  # type: ignore[arg-type]


def test_one_off_trigger_completes_schedule() -> None:
    """После срабатывания разовое расписание становится выполненным."""
    schedule = CampaignSchedule.create(CAMPAIGN_ID, _one_off(), NOW)

    schedule.mark_triggered(triggered_at=NOW + timedelta(hours=1), next_run_at=None, now=NOW)

    assert schedule.status is ScheduleStatus.COMPLETED
    assert schedule.next_run_at is None
    assert schedule.last_triggered_at == NOW + timedelta(hours=1)


def test_cron_trigger_keeps_schedule_active() -> None:
    """Cron-расписание остается активным и получает следующий запуск."""
    schedule = CampaignSchedule.create(CAMPAIGN_ID, _cron(), NOW)
    next_run_at = NOW + timedelta(days=1)

    schedule.mark_triggered(triggered_at=NOW, next_run_at=next_run_at, now=NOW)

    assert schedule.status is ScheduleStatus.ACTIVE
    assert schedule.next_run_at == next_run_at


def test_cancel_changes_only_active_schedule() -> None:
    """Отмена активного расписания меняет состояние один раз."""
    schedule = CampaignSchedule.create(CAMPAIGN_ID, _one_off(), NOW)

    assert schedule.cancel(NOW) is True
    assert schedule.status is ScheduleStatus.CANCELLED
    assert schedule.next_run_at is None
    assert schedule.cancel(NOW) is False


def test_completed_schedule_cannot_be_cancelled() -> None:
    """Выполненное разовое расписание не отменяется повторно."""
    schedule = CampaignSchedule.create(CAMPAIGN_ID, _one_off(), NOW)
    schedule.mark_triggered(triggered_at=NOW, next_run_at=None, now=NOW)

    assert schedule.cancel(NOW) is False
    assert schedule.status is ScheduleStatus.COMPLETED


def test_reschedule_reactivates_schedule() -> None:
    """Новое расписание возвращает кампанию в активное состояние."""
    schedule = CampaignSchedule.create(CAMPAIGN_ID, _one_off(), NOW)
    schedule.cancel(NOW)

    schedule.reschedule(_cron(), now=NOW, correlation_id="corr-2")

    assert schedule.status is ScheduleStatus.ACTIVE
    assert schedule.schedule.kind is ScheduleKind.CRON
    assert schedule.correlation_id == "corr-2"
