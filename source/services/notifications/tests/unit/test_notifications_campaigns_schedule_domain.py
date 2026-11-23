"""Проверка планирования и отмены кампании."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from notifications.domain import (
    EMAIL_CHANNEL,
    Campaign,
    CampaignId,
    CampaignStatus,
    DebtorSelection,
    InvalidStateError,
    ScheduleKind,
    ScheduleSpec,
    TemplateKey,
    ValidationError,
    create_campaign,
)

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
_DEFAULT_KEY = TemplateKey("payment-reminder")
_DEFAULT_SELECTION = DebtorSelection(criteria={"min_days_overdue": "30"})


def _campaign() -> Campaign:
    """Создать корректную draft-кампанию."""
    return create_campaign(
        campaign_id=CampaignId(uuid4()),
        name="Напоминание о просрочке",
        channel=EMAIL_CHANNEL,
        template_key=_DEFAULT_KEY,
        template_version=1,
        selection=_DEFAULT_SELECTION,
        now=_NOW,
    )


def _one_off(run_at: datetime | None = None) -> ScheduleSpec:
    """Собрать разовое расписание."""
    return ScheduleSpec(
        kind=ScheduleKind.ONE_OFF,
        timezone="Europe/Moscow",
        run_at=run_at or _NOW + timedelta(days=1),
    )


def _cron(cron: str = "0 10 * * 1-5") -> ScheduleSpec:
    """Собрать cron-расписание."""
    return ScheduleSpec(
        kind=ScheduleKind.CRON,
        timezone="Europe/Moscow",
        cron=cron,
    )


def test_schedule_one_off_moves_campaign_to_scheduled() -> None:
    """Разовое расписание переводит draft в scheduled."""
    campaign = _campaign()
    schedule = _one_off()

    campaign.schedule_for(schedule, _NOW)

    assert campaign.status is CampaignStatus.SCHEDULED
    assert campaign.schedule == schedule
    assert campaign.scheduled_at == _NOW
    assert campaign.updated_at == _NOW


def test_schedule_cron_moves_campaign_to_scheduled() -> None:
    """Cron-расписание сохраняется в кампании."""
    campaign = _campaign()
    schedule = _cron()

    campaign.schedule_for(schedule, _NOW)

    assert campaign.status is CampaignStatus.SCHEDULED
    assert campaign.schedule == schedule


@pytest.mark.parametrize(
    "schedule",
    [
        ScheduleSpec(kind=ScheduleKind.ONE_OFF, timezone="Unknown/Zone", run_at=_NOW),
        ScheduleSpec(kind=ScheduleKind.ONE_OFF, timezone="Europe/Moscow", run_at=None),
        ScheduleSpec(
            kind=ScheduleKind.ONE_OFF,
            timezone="Europe/Moscow",
            run_at=_NOW - timedelta(minutes=1),
        ),
        ScheduleSpec(
            kind=ScheduleKind.ONE_OFF,
            timezone="Europe/Moscow",
            run_at=_NOW + timedelta(days=1),
            cron="0 10 * * *",
        ),
        ScheduleSpec(kind=ScheduleKind.CRON, timezone="Europe/Moscow", cron=None),
        ScheduleSpec(kind=ScheduleKind.CRON, timezone="Europe/Moscow", cron="0 10 * *"),
        ScheduleSpec(kind=ScheduleKind.CRON, timezone="Europe/Moscow", cron="0 10 * * MON"),
        ScheduleSpec(
            kind=ScheduleKind.CRON,
            timezone="Europe/Moscow",
            cron="0 10 * * *",
            run_at=_NOW + timedelta(days=1),
        ),
    ],
)
def test_schedule_rejects_invalid_rules(schedule: ScheduleSpec) -> None:
    """Некорректное расписание не меняет кампанию."""
    campaign = _campaign()

    with pytest.raises(ValidationError):
        campaign.schedule_for(schedule, _NOW)

    assert campaign.status is CampaignStatus.DRAFT
    assert campaign.schedule is None


def test_schedule_requires_draft() -> None:
    """Запланировать можно только draft-кампанию."""
    campaign = _campaign()
    campaign.status = CampaignStatus.SCHEDULED

    with pytest.raises(InvalidStateError):
        campaign.schedule_for(_one_off(), _NOW)


def test_cancel_scheduled_campaign() -> None:
    """Отмена переводит scheduled в cancelled."""
    campaign = _campaign()
    campaign.schedule_for(_one_off(), _NOW)
    later = _NOW + timedelta(minutes=5)

    campaign.cancel(later)

    assert campaign.status is CampaignStatus.CANCELLED
    assert campaign.cancelled_at == later
    assert campaign.finished_at == later
    assert campaign.updated_at == later


def test_cancel_requires_scheduled() -> None:
    """Отменить можно только запланированную кампанию."""
    campaign = _campaign()

    with pytest.raises(InvalidStateError):
        campaign.cancel(_NOW)


def test_cancel_is_not_repeatable() -> None:
    """Повторная отмена уже отмененной кампании запрещена."""
    campaign = _campaign()
    campaign.schedule_for(_one_off(), _NOW)
    campaign.cancel(_NOW)

    with pytest.raises(InvalidStateError):
        campaign.cancel(_NOW)
