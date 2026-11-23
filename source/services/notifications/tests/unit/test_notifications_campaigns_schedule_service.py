"""Проверка сценариев планирования и отмены кампании."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest

from notifications.application.campaigns import CreateCampaignCommand
from notifications.application.common import RequestContext
from notifications.domain import (
    EMAIL_CHANNEL,
    AuditAction,
    Campaign,
    CampaignId,
    CampaignStatus,
    DebtorSelection,
    InvalidStateError,
    NotFoundError,
    ScheduleKind,
    ScheduleSpec,
    TemplateKey,
    ValidationError,
)

_CONTEXT = RequestContext(correlation_id="corr-schedule", trace_id="trace-schedule")
_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _one_off() -> ScheduleSpec:
    """Собрать разовое расписание в будущем."""
    return ScheduleSpec(
        kind=ScheduleKind.ONE_OFF,
        timezone="Europe/Moscow",
        run_at=_NOW + timedelta(days=1),
    )


async def _campaign(campaign_harness: Any) -> Campaign:
    """Создать draft-кампанию с активным шаблоном."""
    await campaign_harness.create_active_template()
    campaign_harness.audits.clear()
    campaign = await campaign_harness.campaign_service.create_campaign(
        CreateCampaignCommand(
            name="Кампания для расписания",
            channel=EMAIL_CHANNEL,
            template_key=TemplateKey("payment-reminder"),
            template_version=1,
            selection=DebtorSelection(criteria={"min_days_overdue": "30"}),
        ),
        _CONTEXT,
    )
    return cast(Campaign, campaign)


async def test_schedule_campaign_writes_state_audit_and_event(
    campaign_harness: Any,
) -> None:
    """Планирование сохраняет статус, аудит и campaign.scheduled."""
    campaign = await _campaign(campaign_harness)
    campaign_harness.audits.clear()

    scheduled = await campaign_harness.campaign_service.schedule_campaign(
        campaign.id,
        _one_off(),
        _CONTEXT,
    )

    assert scheduled.status is CampaignStatus.SCHEDULED
    assert scheduled.schedule is not None
    assert scheduled.schedule.kind is ScheduleKind.ONE_OFF
    assert scheduled.scheduled_at == campaign_harness.clock.now()
    stored = await campaign_harness.campaigns.get(campaign.id)
    assert stored is not None
    assert stored.status is CampaignStatus.SCHEDULED
    assert len(campaign_harness.audits) == 1
    audit = campaign_harness.audits[0]
    assert audit.action is AuditAction.CAMPAIGN_SCHEDULED
    assert audit.details["schedule_kind"] == "one_off"
    assert audit.details["timezone"] == "Europe/Moscow"
    assert len(campaign_harness.scheduled_events) == 1
    event = campaign_harness.scheduled_events[0]
    assert event.campaign_id == campaign.id
    assert event.schedule.kind is ScheduleKind.ONE_OFF


async def test_schedule_campaign_rejects_invalid_rule(
    campaign_harness: Any,
) -> None:
    """Некорректное расписание не создает событий."""
    campaign = await _campaign(campaign_harness)
    campaign_harness.audits.clear()
    invalid = ScheduleSpec(
        kind=ScheduleKind.ONE_OFF,
        timezone="Europe/Moscow",
        run_at=_NOW - timedelta(minutes=1),
    )

    with pytest.raises(ValidationError):
        await campaign_harness.campaign_service.schedule_campaign(
            campaign.id,
            invalid,
            _CONTEXT,
        )

    assert campaign_harness.audits == []
    assert campaign_harness.scheduled_events == []


async def test_schedule_missing_campaign_raises_not_found(
    campaign_harness: Any,
) -> None:
    """Планирование отсутствующей кампании дает NotFoundError."""
    with pytest.raises(NotFoundError):
        await campaign_harness.campaign_service.schedule_campaign(
            CampaignId(uuid4()),
            _one_off(),
            _CONTEXT,
        )


async def test_schedule_twice_is_rejected(campaign_harness: Any) -> None:
    """Повторное планирование уже запланированной кампании запрещено."""
    campaign = await _campaign(campaign_harness)
    await campaign_harness.campaign_service.schedule_campaign(
        campaign.id,
        _one_off(),
        _CONTEXT,
    )

    with pytest.raises(InvalidStateError):
        await campaign_harness.campaign_service.schedule_campaign(
            campaign.id,
            _one_off(),
            _CONTEXT,
        )


async def test_cancel_campaign_writes_state_audit_and_event(
    campaign_harness: Any,
) -> None:
    """Отмена сохраняет статус, аудит и campaign.cancelled."""
    campaign = await _campaign(campaign_harness)
    await campaign_harness.campaign_service.schedule_campaign(
        campaign.id,
        _one_off(),
        _CONTEXT,
    )
    campaign_harness.audits.clear()
    later = campaign_harness.clock.now() + timedelta(minutes=5)
    campaign_harness.clock.set(later)

    cancelled = await campaign_harness.campaign_service.cancel_campaign(
        campaign.id,
        _CONTEXT,
    )

    assert cancelled.status is CampaignStatus.CANCELLED
    assert cancelled.cancelled_at == later
    assert cancelled.finished_at == later
    stored = await campaign_harness.campaigns.get(campaign.id)
    assert stored is not None
    assert stored.status is CampaignStatus.CANCELLED
    assert len(campaign_harness.audits) == 1
    audit = campaign_harness.audits[0]
    assert audit.action is AuditAction.CAMPAIGN_CANCELLED
    assert audit.details["status"] == "cancelled"
    assert len(campaign_harness.cancelled_events) == 1
    event = campaign_harness.cancelled_events[0]
    assert event.campaign_id == campaign.id
    assert event.occurred_at == later


async def test_cancel_draft_campaign_is_rejected(campaign_harness: Any) -> None:
    """Отмена draft-кампании запрещена."""
    campaign = await _campaign(campaign_harness)

    with pytest.raises(InvalidStateError):
        await campaign_harness.campaign_service.cancel_campaign(
            campaign.id,
            _CONTEXT,
        )


async def test_cancel_missing_campaign_raises_not_found(
    campaign_harness: Any,
) -> None:
    """Отмена отсутствующей кампании дает NotFoundError."""
    with pytest.raises(NotFoundError):
        await campaign_harness.campaign_service.cancel_campaign(
            CampaignId(uuid4()),
            _CONTEXT,
        )
