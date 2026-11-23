"""Проверка переходов сообщения при результатах отправки."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from notifications.domain import (
    EMAIL_CHANNEL,
    CampaignId,
    DebtorId,
    DeliveryOutcome,
    IdempotencyKey,
    MessageId,
    MessageStatus,
    NotificationMessage,
    Recipient,
    TemplateKey,
)

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _message(status: MessageStatus = MessageStatus.QUEUED) -> NotificationMessage:
    """Создать сообщение в нужном статусе."""
    return NotificationMessage(
        id=MessageId(uuid4()),
        campaign_id=CampaignId(uuid4()),
        debtor_id=DebtorId("ABS-1"),
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey("payment-reminder"),
        template_version=1,
        variables={"debtor_name": "Иван"},
        recipient=Recipient(channel=EMAIL_CHANNEL, address="debtor@example.test"),
        idempotency_key=IdempotencyKey("key"),
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


def test_mark_sent_sets_terminal_state() -> None:
    """Успешная отправка закрывает сообщение."""
    message = _message()

    assert message.mark_sent(attempt_number=2, occurred_at=_NOW) is True
    assert message.status is MessageStatus.SENT
    assert message.attempt_count == 2
    assert message.sent_at == _NOW
    assert message.last_attempt_at == _NOW
    assert message.next_attempt_at is None


def test_mark_sent_ignores_terminal_message() -> None:
    """Повторный результат не меняет завершенное сообщение."""
    message = _message(MessageStatus.SENT)

    assert message.mark_sent(attempt_number=1, occurred_at=_NOW) is False


def test_mark_failed_schedules_retry() -> None:
    """Временная ошибка возвращает сообщение в очередь."""
    message = _message()
    retry_at = _NOW.replace(minute=5)

    assert (
        message.mark_failed(
            attempt_number=1,
            occurred_at=_NOW,
            error_code="SMTP_TIMEOUT",
            error_message="timeout",
            retry_at=retry_at,
        )
        is True
    )
    assert message.status is MessageStatus.QUEUED
    assert message.attempt_count == 1
    assert message.next_attempt_at == retry_at
    assert message.last_error_code == "SMTP_TIMEOUT"
    assert message.failed_at is None


def test_mark_failed_finishes_message() -> None:
    """Без повтора сообщение переходит в failed."""
    message = _message()

    message.mark_failed(
        attempt_number=3,
        occurred_at=_NOW,
        error_code="SMTP_REJECTED",
        error_message="rejected",
        retry_at=None,
    )

    assert message.status is MessageStatus.FAILED
    assert message.failed_at == _NOW
    assert message.next_attempt_at is None


def test_cancel_if_pending() -> None:
    """Неотправленное сообщение можно отменить."""
    message = _message()

    assert message.cancel_if_pending() is True
    assert message.status is MessageStatus.CANCELLED
    assert message.next_attempt_at is None


def test_cancel_if_pending_ignores_sent() -> None:
    """Отправленное сообщение не отменяется."""
    message = _message(MessageStatus.SENT)

    assert message.cancel_if_pending() is False


def test_outcome_values_are_stable() -> None:
    """Классификация ошибок соответствует контракту."""
    assert DeliveryOutcome.SENT.value == "sent"
    assert DeliveryOutcome.TRANSIENT_FAILURE.value == "transient_failure"
    assert DeliveryOutcome.PERMANENT_FAILURE.value == "permanent_failure"
    assert DeliveryOutcome.RATE_LIMITED.value == "rate_limited"


def test_message_terminal_statuses() -> None:
    """Завершенные сообщения не меняют статус."""
    for status in (MessageStatus.SENT, MessageStatus.FAILED, MessageStatus.CANCELLED):
        message = _message(status)
        assert (
            message.mark_failed(
                attempt_number=2,
                occurred_at=_NOW,
                error_code=None,
                error_message=None,
                retry_at=None,
            )
            is False
        )


@pytest.mark.parametrize("status", [MessageStatus.PENDING, MessageStatus.QUEUED])
def test_cancel_pending_statuses(status: MessageStatus) -> None:
    """Отменяются только pending и queued."""
    message = _message(status)
    assert message.cancel_if_pending() is True
