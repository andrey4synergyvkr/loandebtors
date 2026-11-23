"""Проверка обработки message.sent и message.failed."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from notifications.application.common import RequestContext
from notifications.application.message_results import MessageResultService
from notifications.config import Settings
from notifications.domain import (
    EMAIL_CHANNEL,
    AuditAction,
    Campaign,
    CampaignId,
    CampaignStatus,
    DebtorId,
    DebtorSelection,
    DeliveryOutcome,
    IdempotencyKey,
    MessageFailed,
    MessageId,
    MessageSent,
    MessageStatus,
    NotificationMessage,
    Recipient,
    TemplateKey,
    create_campaign,
)

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
_CONTEXT = RequestContext(correlation_id="corr-result", trace_id="trace-result")


def _campaign() -> Campaign:
    """Создать выполняющуюся кампанию."""
    campaign = create_campaign(
        campaign_id=CampaignId(uuid4()),
        name="Кампания результатов",
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey("payment-reminder"),
        template_version=1,
        selection=DebtorSelection(criteria={"min_days_overdue": "30"}),
        now=_NOW,
    )
    campaign.mark_running(_NOW)
    campaign.mark_messages_created(_NOW)
    return campaign


def _message(
    campaign: Campaign,
    status: MessageStatus = MessageStatus.QUEUED,
    max_attempts: int = 3,
) -> NotificationMessage:
    """Создать сообщение кампании."""
    return NotificationMessage(
        id=MessageId(uuid4()),
        campaign_id=campaign.id,
        debtor_id=DebtorId("ABS-1"),
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey("payment-reminder"),
        template_version=1,
        variables={"debtor_name": "Иван"},
        recipient=Recipient(channel=EMAIL_CHANNEL, address="debtor@example.test"),
        idempotency_key=IdempotencyKey(str(uuid4())),
        status=status,
        attempt_count=0,
        max_attempts=max_attempts,
        created_at=_NOW,
        queued_at=_NOW,
        last_attempt_at=None,
        sent_at=None,
        failed_at=None,
        next_attempt_at=None,
        last_error_code=None,
        last_error_message=None,
    )


def _service(harness: Any) -> MessageResultService:
    """Собрать сервис результатов."""
    return MessageResultService(
        uow_factory=harness.factory,
        clock=harness.clock,
        settings=Settings(
            message_max_attempts=3,
            message_retry_base_seconds=10.0,
            message_retry_max_seconds=60.0,
        ),
    )


async def _prepare(harness: Any, count: int = 1) -> tuple[Campaign, list[NotificationMessage]]:
    """Сохранить кампанию и сообщения в тестовых репозиториях."""
    campaign = _campaign()
    await harness.campaigns.add(campaign)
    messages = [_message(campaign) for _ in range(count)]
    await harness.messages.add_many(messages)
    harness.audits.clear()
    harness.message_commands.clear()
    harness.message_command_delays.clear()
    return campaign, messages


async def test_sent_message_completes_campaign(campaign_harness: Any) -> None:
    """Успешный результат закрывает сообщение и кампанию."""
    campaign, messages = await _prepare(campaign_harness)
    service = _service(campaign_harness)

    await service.handle_sent(
        MessageSent(
            message_id=messages[0].id,
            campaign_id=campaign.id,
            channel=EMAIL_CHANNEL,
            attempt_number=1,
            provider_message_id="smtp-1",
            occurred_at=_NOW,
        ),
        _CONTEXT,
    )

    stored = await campaign_harness.messages.get(messages[0].id)
    assert stored is not None
    assert stored.status is MessageStatus.SENT
    assert len(campaign_harness.attempts.items) == 1
    stored_campaign = await campaign_harness.campaigns.get(campaign.id)
    assert stored_campaign.status is CampaignStatus.COMPLETED
    actions = [event.action for event in campaign_harness.audits]
    assert actions == [AuditAction.MESSAGE_SENT, AuditAction.CAMPAIGN_COMPLETED]


async def test_campaign_waits_for_other_messages(campaign_harness: Any) -> None:
    """Кампания не завершается, пока есть незавершенные сообщения."""
    campaign, messages = await _prepare(campaign_harness, count=2)
    service = _service(campaign_harness)

    await service.handle_sent(
        MessageSent(
            message_id=messages[0].id,
            campaign_id=campaign.id,
            channel=EMAIL_CHANNEL,
            attempt_number=1,
            provider_message_id=None,
            occurred_at=_NOW,
        ),
        _CONTEXT,
    )

    stored_campaign = await campaign_harness.campaigns.get(campaign.id)
    assert stored_campaign.status is CampaignStatus.RUNNING


async def test_last_result_completes_campaign_once(campaign_harness: Any) -> None:
    """Последний результат завершает кампанию ровно один раз."""
    campaign, messages = await _prepare(campaign_harness, count=2)
    service = _service(campaign_harness)

    for message in messages:
        await service.handle_sent(
            MessageSent(
                message_id=message.id,
                campaign_id=campaign.id,
                channel=EMAIL_CHANNEL,
                attempt_number=1,
                provider_message_id=None,
                occurred_at=_NOW,
            ),
            _CONTEXT,
        )

    stored_campaign = await campaign_harness.campaigns.get(campaign.id)
    assert stored_campaign.status is CampaignStatus.COMPLETED
    completed = [event for event in campaign_harness.audits if event.action is AuditAction.CAMPAIGN_COMPLETED]
    assert len(completed) == 1


async def test_transient_failure_schedules_retry(campaign_harness: Any) -> None:
    """Временная ошибка пишет отложенную команду message.send."""
    campaign, messages = await _prepare(campaign_harness)
    service = _service(campaign_harness)

    await service.handle_failed(
        MessageFailed(
            message_id=messages[0].id,
            campaign_id=campaign.id,
            channel=EMAIL_CHANNEL,
            attempt_number=1,
            outcome=DeliveryOutcome.TRANSIENT_FAILURE,
            retryable=True,
            error_code="SMTP_TIMEOUT",
            error_message="timeout",
            occurred_at=_NOW,
        ),
        _CONTEXT,
    )

    stored = await campaign_harness.messages.get(messages[0].id)
    assert stored.status is MessageStatus.QUEUED
    assert stored.next_attempt_at == _NOW + timedelta(seconds=10)
    assert len(campaign_harness.message_commands) == 1
    assert campaign_harness.message_command_delays == [stored.next_attempt_at]
    assert len(campaign_harness.attempts.items) == 1
    stored_campaign = await campaign_harness.campaigns.get(campaign.id)
    assert stored_campaign.status is CampaignStatus.RUNNING


async def test_permanent_failure_finishes_campaign(campaign_harness: Any) -> None:
    """Постоянная ошибка закрывает сообщение и кампанию."""
    campaign, messages = await _prepare(campaign_harness)
    service = _service(campaign_harness)

    await service.handle_failed(
        MessageFailed(
            message_id=messages[0].id,
            campaign_id=campaign.id,
            channel=EMAIL_CHANNEL,
            attempt_number=1,
            outcome=DeliveryOutcome.PERMANENT_FAILURE,
            retryable=False,
            error_code="SMTP_REJECTED",
            error_message="rejected",
            occurred_at=_NOW,
        ),
        _CONTEXT,
    )

    stored = await campaign_harness.messages.get(messages[0].id)
    assert stored.status is MessageStatus.FAILED
    assert campaign_harness.message_commands == []
    stored_campaign = await campaign_harness.campaigns.get(campaign.id)
    assert stored_campaign.status is CampaignStatus.COMPLETED
    assert campaign_harness.audits[-1].action is AuditAction.CAMPAIGN_COMPLETED


async def test_exhausted_retries_finish_message(campaign_harness: Any) -> None:
    """После исчерпания попыток повтор не планируется."""
    campaign, messages = await _prepare(campaign_harness)
    service = _service(campaign_harness)

    await service.handle_failed(
        MessageFailed(
            message_id=messages[0].id,
            campaign_id=campaign.id,
            channel=EMAIL_CHANNEL,
            attempt_number=3,
            outcome=DeliveryOutcome.TRANSIENT_FAILURE,
            retryable=True,
            error_code="SMTP_TIMEOUT",
            error_message="timeout",
            occurred_at=_NOW,
        ),
        _CONTEXT,
    )

    stored = await campaign_harness.messages.get(messages[0].id)
    assert stored.status is MessageStatus.FAILED
    assert campaign_harness.message_commands == []


async def test_duplicate_result_is_ignored(campaign_harness: Any) -> None:
    """Повторный результат не создает вторую попытку."""
    campaign, messages = await _prepare(campaign_harness)
    service = _service(campaign_harness)
    event = MessageFailed(
        message_id=messages[0].id,
        campaign_id=campaign.id,
        channel=EMAIL_CHANNEL,
        attempt_number=1,
        outcome=DeliveryOutcome.TRANSIENT_FAILURE,
        retryable=True,
        error_code="SMTP_TIMEOUT",
        error_message="timeout",
        occurred_at=_NOW,
    )

    await service.handle_failed(event, _CONTEXT)
    await service.handle_failed(event, _CONTEXT)

    assert len(campaign_harness.attempts.items) == 1
    assert len(campaign_harness.message_commands) == 1


async def test_cancelled_message_ignores_result(campaign_harness: Any) -> None:
    """Результат по отмененному сообщению не применяется."""
    campaign, messages = await _prepare(campaign_harness)
    message = messages[0]
    message.cancel_if_pending()
    await campaign_harness.messages.save(message)
    service = _service(campaign_harness)

    await service.handle_sent(
        MessageSent(
            message_id=message.id,
            campaign_id=campaign.id,
            channel=EMAIL_CHANNEL,
            attempt_number=1,
            provider_message_id=None,
            occurred_at=_NOW,
        ),
        _CONTEXT,
    )

    stored = await campaign_harness.messages.get(message.id)
    assert stored.status is MessageStatus.CANCELLED
    assert campaign_harness.attempts.items == []
