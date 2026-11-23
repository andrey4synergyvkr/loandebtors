"""Проверка переходов кампании при запуске."""

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
    create_campaign,
)

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _campaign() -> Campaign:
    """Создать draft-кампанию."""
    return create_campaign(
        campaign_id=CampaignId(uuid4()),
        name="Кампания запуска",
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey("payment-reminder"),
        template_version=1,
        selection=DebtorSelection(criteria={"min_days_overdue": "30"}),
        now=_NOW,
    )


def test_new_campaign_has_no_messages_timestamp() -> None:
    """До запуска сообщения не создавались."""
    assert _campaign().messages_created_at is None


def test_mark_running_from_draft() -> None:
    """Draft переходит в running и фиксирует старт."""
    campaign = _campaign()

    assert campaign.mark_running(_NOW) is True
    assert campaign.status is CampaignStatus.RUNNING
    assert campaign.started_at == _NOW
    assert campaign.updated_at == _NOW


def test_mark_running_from_scheduled() -> None:
    """Запланированная кампания переходит в running."""
    campaign = _campaign()
    campaign.schedule_for(
        ScheduleSpec(
            kind=ScheduleKind.ONE_OFF,
            timezone="Europe/Moscow",
            run_at=_NOW + timedelta(days=1),
        ),
        _NOW,
    )

    assert campaign.mark_running(_NOW) is True
    assert campaign.status is CampaignStatus.RUNNING


def test_mark_running_is_idempotent() -> None:
    """Повтор для running не меняет статус."""
    campaign = _campaign()
    campaign.mark_running(_NOW)

    assert campaign.mark_running(_NOW) is False


def test_mark_running_rejects_terminal_status() -> None:
    """Завершенную кампанию запустить нельзя."""
    campaign = _campaign()
    campaign.status = CampaignStatus.CANCELLED

    with pytest.raises(InvalidStateError):
        campaign.mark_running(_NOW)


def test_mark_messages_created_requires_running() -> None:
    """Отметка создания сообщений доступна только running."""
    campaign = _campaign()

    with pytest.raises(InvalidStateError):
        campaign.mark_messages_created(_NOW)

    campaign.mark_running(_NOW)
    campaign.mark_messages_created(_NOW)
    assert campaign.messages_created_at == _NOW


def test_fail_sets_reason_and_finish_time() -> None:
    """Ошибка переводит кампанию в failed."""
    campaign = _campaign()
    campaign.mark_running(_NOW)

    campaign.fail("АБС недоступна", _NOW)

    assert campaign.status is CampaignStatus.FAILED
    assert campaign.failure_reason == "АБС недоступна"
    assert campaign.finished_at == _NOW


def test_fail_rejects_terminal_status() -> None:
    """Повторный fail для завершенной кампании запрещен."""
    campaign = _campaign()
    campaign.mark_running(_NOW)
    campaign.fail("Ошибка", _NOW)

    with pytest.raises(InvalidStateError):
        campaign.fail("Еще ошибка", _NOW)
