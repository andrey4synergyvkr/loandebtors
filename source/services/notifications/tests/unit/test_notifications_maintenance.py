"""Проверка фонового обслуживания и восстановления."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from notifications.application.maintenance import MaintenanceResult, MaintenanceService
from notifications.domain import (
    EMAIL_CHANNEL,
    Campaign,
    CampaignId,
    CampaignStatus,
    DebtorId,
    DebtorSelection,
    IdempotencyKey,
    MessageId,
    MessageStatus,
    NotificationMessage,
    Recipient,
    TemplateKey,
    create_campaign,
)
from notifications.ports import ExhaustedMessageCommand

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _campaign(status: CampaignStatus = CampaignStatus.RUNNING) -> Campaign:
    """Создать кампанию в нужном статусе."""
    campaign = create_campaign(
        campaign_id=CampaignId(uuid4()),
        name="Кампания обслуживания",
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey("payment-reminder"),
        template_version=1,
        selection=DebtorSelection(criteria={}),
        now=_NOW,
    )
    campaign.status = status
    return campaign


def _message(campaign: Campaign) -> NotificationMessage:
    """Создать сообщение для повтора."""
    return NotificationMessage(
        id=MessageId(uuid4()),
        campaign_id=campaign.id,
        debtor_id=DebtorId("ABS-1"),
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey("payment-reminder"),
        template_version=1,
        variables={},
        recipient=Recipient(channel=EMAIL_CHANNEL, address="debtor@example.test"),
        idempotency_key=IdempotencyKey(str(uuid4())),
        status=MessageStatus.QUEUED,
        attempt_count=1,
        max_attempts=3,
        created_at=_NOW,
        queued_at=_NOW,
        last_attempt_at=_NOW,
        sent_at=None,
        failed_at=None,
        next_attempt_at=_NOW,
        last_error_code=None,
        last_error_message=None,
    )


def _service(harness: Any) -> MaintenanceService:
    """Собрать сервис обслуживания."""
    return MaintenanceService(
        uow_factory=harness.factory,
        clock=harness.clock,
        retention_days=30,
        recovery_grace_seconds=300,
        batch_size=100,
        outbox_max_attempts=10,
    )


async def test_retention_and_recovery(campaign_harness: Any) -> None:
    """Итерация удаляет старое и восстанавливает зависшие состояния."""
    service = _service(campaign_harness)
    campaign = _campaign()
    message = _message(campaign)
    stuck = _campaign()
    completable = _campaign()
    store = campaign_harness.maintenance
    store.retry_due = [message]
    store.stuck_campaigns = [stuck]
    store.completable_campaigns = [completable]
    store.deleted_outbox = 7
    store.deleted_attempts = 3
    await campaign_harness.campaigns.add(completable)

    result = await service.run_once()

    assert result.requeued_messages == 1
    assert result.requeued_campaigns == 1
    assert result.completed_campaigns == 1
    assert result.deleted_outbox == 7
    assert result.deleted_attempts == 3
    assert len(campaign_harness.message_commands) == 1
    assert len(campaign_harness.start_events) == 1
    stored = await campaign_harness.campaigns.get(completable.id)
    assert stored is not None
    assert stored.status is CampaignStatus.COMPLETED


async def test_empty_iteration_is_noop(campaign_harness: Any) -> None:
    """Пустая итерация ничего не меняет."""
    service = _service(campaign_harness)

    result = await service.run_once()

    assert result == MaintenanceResult(0, 0, 0, 0, 0, 0)
    assert campaign_harness.message_commands == []
    assert campaign_harness.start_events == []


async def test_exhausted_outbox_fails_message_and_completes_campaign(
    campaign_harness: Any,
) -> None:
    """Исчерпание outbox закрывает сообщение и кампанию с audit-событием."""
    service = _service(campaign_harness)
    campaign = _campaign()
    message = _message(campaign)
    await campaign_harness.campaigns.add(campaign)
    await campaign_harness.messages.add_many([message])
    command = ExhaustedMessageCommand(outbox_id=uuid4(), message_id=message.id)
    campaign_harness.maintenance.exhausted_commands = [command]
    campaign_harness.maintenance.completable_campaigns = [campaign]

    result = await service.run_once()

    assert result.exhausted_messages == 1
    assert result.completed_campaigns == 1
    stored = await campaign_harness.messages.get(message.id)
    assert stored is not None
    assert stored.status is MessageStatus.FAILED
    assert stored.last_error_code == "outbox_publish_exhausted"
    assert campaign_harness.maintenance.failed_outbox == [command.outbox_id]
    assert any(event.action.value == "message.failed" for event in campaign_harness.audits)
    completed = await campaign_harness.campaigns.get(campaign.id)
    assert completed is not None
    assert completed.status is CampaignStatus.COMPLETED
