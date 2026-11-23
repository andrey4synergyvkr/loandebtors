"""Проверка отмены выполняющейся кампании."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from notifications.application.campaigns import CreateCampaignCommand
from notifications.application.common import RequestContext
from notifications.domain import (
    EMAIL_CHANNEL,
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
)

_CONTEXT = RequestContext(correlation_id="corr-cancel-running", trace_id=None)
_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _message(campaign_id: CampaignId, status: MessageStatus) -> NotificationMessage:
    """Создать сообщение кампании в нужном статусе."""
    return NotificationMessage(
        id=MessageId(uuid4()),
        campaign_id=campaign_id,
        debtor_id=DebtorId("ABS-1"),
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey("payment-reminder"),
        template_version=1,
        variables={},
        recipient=Recipient(channel=EMAIL_CHANNEL, address="debtor@example.test"),
        idempotency_key=IdempotencyKey(str(uuid4())),
        status=status,
        attempt_count=0,
        max_attempts=3,
        created_at=_NOW,
        queued_at=_NOW,
        last_attempt_at=None,
        sent_at=None,
        failed_at=None,
        next_attempt_at=None,
        last_error_code=None,
        last_error_message=None,
    )


async def test_cancel_running_cancels_pending_messages(campaign_harness: Any) -> None:
    """Отмена выполняющейся кампании закрывает неотправленные сообщения."""
    await campaign_harness.create_active_template()
    campaign = await campaign_harness.campaign_service.create_campaign(
        CreateCampaignCommand(
            name="Кампания отмены",
            channel=EMAIL_CHANNEL,
            template_key=TemplateKey("payment-reminder"),
            template_version=1,
            selection=DebtorSelection(criteria={"min_days_overdue": "30"}),
        ),
        _CONTEXT,
    )
    await campaign_harness.campaign_service.start_campaign(campaign.id, _CONTEXT)
    queued = _message(campaign.id, MessageStatus.QUEUED)
    pending = _message(campaign.id, MessageStatus.PENDING)
    sent = _message(campaign.id, MessageStatus.SENT)
    await campaign_harness.messages.add_many([queued, pending, sent])
    campaign_harness.audits.clear()
    campaign_harness.cancelled_events.clear()

    cancelled = await campaign_harness.campaign_service.cancel_campaign(
        campaign.id,
        _CONTEXT,
    )

    assert cancelled.status is CampaignStatus.CANCELLED
    for message in (queued, pending):
        stored = await campaign_harness.messages.get(message.id)
        assert stored.status is MessageStatus.CANCELLED
    stored_sent = await campaign_harness.messages.get(sent.id)
    assert stored_sent.status is MessageStatus.SENT
    assert campaign_harness.cancelled_events == []
    audit = campaign_harness.audits[-1]
    assert audit.action.value == "campaign.cancelled"
    assert audit.details["cancelled_messages"] == "2"


async def test_cancel_running_without_messages(campaign_harness: Any) -> None:
    """Отмена выполняющейся кампании без сообщений завершается успешно."""
    await campaign_harness.create_active_template()
    campaign = await campaign_harness.campaign_service.create_campaign(
        CreateCampaignCommand(
            name="Пустая кампания",
            channel=EMAIL_CHANNEL,
            template_key=TemplateKey("payment-reminder"),
            template_version=1,
            selection=DebtorSelection(criteria={}),
        ),
        _CONTEXT,
    )
    await campaign_harness.campaign_service.start_campaign(campaign.id, _CONTEXT)

    cancelled = await campaign_harness.campaign_service.cancel_campaign(
        campaign.id,
        _CONTEXT,
    )

    assert cancelled.status is CampaignStatus.CANCELLED
