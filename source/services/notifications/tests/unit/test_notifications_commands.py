"""Проверка разбора команд notification.commands."""

import json

import pytest

from notifications.adapters.messaging.commands import (
    decode_for_dead_letter,
    parse_result_command,
    parse_start_command,
    retry_attempts,
    should_dead_letter,
)
from notifications.domain import DeliveryOutcome, MessageFailed, MessageSent, ValidationError


def _body(**overrides: object) -> bytes:
    """Собрать тело campaign.start."""
    payload: dict[str, object] = {
        "campaign_id": "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d",
        "scheduled_for": "2026-12-01T10:00:00Z",
        "occurred_at": "2026-11-22T12:00:00Z",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def test_parse_start_command() -> None:
    """Команда campaign.start разбирается в доменное событие."""
    command = parse_start_command("campaign.start", _body())

    assert str(command.campaign_id) == "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"
    assert command.scheduled_for.tzinfo is not None


def test_parse_start_accepts_retry_queue_routing_key() -> None:
    """После retry сообщение приходит с routing key очереди."""
    command = parse_start_command("notification.commands", _body())

    assert str(command.campaign_id) == "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"


def test_parse_start_rejects_unknown_routing_key() -> None:
    """Неизвестный routing key отклоняется."""
    with pytest.raises(ValidationError):
        parse_start_command("campaign.scheduled", _body())


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        _body(scheduled_for="2026-12-01T10:00:00"),
        _body(extra="field"),
    ],
)
def test_parse_start_rejects_invalid_body(body: bytes) -> None:
    """Некорректное тело сообщения отклоняется."""
    with pytest.raises(ValidationError):
        parse_start_command("campaign.start", body)


def test_retry_attempts_uses_notification_retry_queue() -> None:
    """Повторы считаются по x-death для retry-очереди конкретного потребителя."""
    headers = {
        "x-death": [
            {"queue": "notification.commands.retry", "count": 2},
            {"queue": "notification.results.retry", "count": 4},
            {"queue": "other.retry", "count": 5},
        ]
    }

    assert retry_attempts(headers, "notification.commands") == 2
    assert retry_attempts(headers, "notification.results") == 4
    assert should_dead_letter(headers, 2, "notification.commands") is True
    assert should_dead_letter(headers, 3, "notification.commands") is False
    assert should_dead_letter(headers, 4, "notification.results") is True


def test_decode_for_dead_letter_keeps_json() -> None:
    """Валидный JSON сохраняется, мусор упаковывается в raw."""
    assert decode_for_dead_letter(b'{"a": 1}') == {"a": 1}
    assert decode_for_dead_letter(b"\xff") == {"raw": "\ufffd"}


def _sent_body() -> bytes:
    """Собрать тело message.sent."""
    return json.dumps(
        {
            "message_id": "5a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
            "campaign_id": "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d",
            "channel": "email",
            "attempt_number": 1,
            "provider_message_id": "smtp-1",
            "occurred_at": "2026-11-22T12:00:00Z",
        }
    ).encode("utf-8")


@pytest.mark.parametrize(
    "body",
    [
        _sent_body().replace(b'"attempt_number": 1', b'"attempt_number": 0'),
        _sent_body().replace(b'"channel": "email"', b'"channel": "Email"'),
    ],
)
def test_parse_result_rejects_invalid_attempt_and_channel(body: bytes) -> None:
    """Номер попытки и код канала проверяются до домена."""
    with pytest.raises(ValidationError):
        parse_result_command("message.sent", body)


def _failed_body(outcome: str = "transient_failure") -> bytes:
    """Собрать тело message.failed."""
    return json.dumps(
        {
            "message_id": "5a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
            "campaign_id": "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d",
            "channel": "email",
            "attempt_number": 2,
            "outcome": outcome,
            "retryable": True,
            "error_code": "SMTP_TIMEOUT",
            "error_message": "timeout",
            "occurred_at": "2026-11-22T12:00:00Z",
        }
    ).encode("utf-8")


def test_parse_message_sent() -> None:
    """message.sent разбирается в доменное событие."""
    command = parse_result_command("message.sent", _sent_body())

    assert isinstance(command, MessageSent)
    assert command.attempt_number == 1
    assert command.provider_message_id == "smtp-1"


def test_parse_message_failed() -> None:
    """message.failed разбирается в доменное событие."""
    command = parse_result_command("message.failed", _failed_body())

    assert isinstance(command, MessageFailed)
    assert command.outcome is DeliveryOutcome.TRANSIENT_FAILURE
    assert command.retryable is True


def test_parse_result_from_retry_queue_infers_type() -> None:
    """После retry тип определяется по телу сообщения."""
    sent = parse_result_command("notification.results", _sent_body())
    failed = parse_result_command("notification.results", _failed_body())

    assert isinstance(sent, MessageSent)
    assert isinstance(failed, MessageFailed)


def test_parse_failed_rejects_sent_outcome() -> None:
    """message.failed не может содержать outcome=sent."""
    with pytest.raises(ValidationError):
        parse_result_command("message.failed", _failed_body("sent"))


def test_parse_result_rejects_unknown_routing_key() -> None:
    """Неизвестный routing key отклоняется."""
    with pytest.raises(ValidationError):
        parse_result_command("unknown", _sent_body())
