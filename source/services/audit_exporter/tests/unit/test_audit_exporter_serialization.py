"""Проверка декодирования и валидации audit.event."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from audit_exporter.adapters.messaging.schemas import AuditEventPayload, to_domain
from audit_exporter.adapters.messaging.serialization import decode_payload
from audit_exporter.domain import AuditAction, AuditActorType, AuditOutcome, ValidationError

_EVENT_ID = "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"
_CAMPAIGN_ID = "5a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def _payload() -> dict[str, object]:
    return {
        "event_id": _EVENT_ID,
        "occurred_at": "2026-11-22T12:00:00Z",
        "service": "notifications",
        "actor": {"type": "system", "identifier": "notifications"},
        "action": "message.sent",
        "entity_type": "message",
        "entity_id": _EVENT_ID,
        "campaign_id": _CAMPAIGN_ID,
        "message_id": _EVENT_ID,
        "channel": "email",
        "outcome": "success",
        "details": {"provider": "mailpit"},
        "correlation_id": "corr-1",
        "trace_id": "1234567890abcdef1234567890abcdef",
    }


def test_decode_payload_returns_mapping() -> None:
    """Валидный JSON-объект декодируется в mapping."""
    assert decode_payload(b'{"event_id":"x"}') == {"event_id": "x"}


def test_decode_payload_rejects_invalid_json() -> None:
    """Невалидный JSON даёт доменную ошибку валидации."""
    with pytest.raises(ValidationError):
        decode_payload(b"not-json")


def test_decode_payload_rejects_non_object() -> None:
    """JSON-массив не является телом audit.event."""
    with pytest.raises(ValidationError):
        decode_payload(b"[]")


def test_payload_maps_to_domain_event() -> None:
    """Поля сообщения переносятся в доменное событие."""
    payload = AuditEventPayload.model_validate(_payload())

    event = to_domain(payload)

    assert event.event_id == UUID(_EVENT_ID)
    assert event.occurred_at == datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    assert event.service == "notifications"
    assert event.actor.type is AuditActorType.SYSTEM
    assert event.action is AuditAction.MESSAGE_SENT
    assert event.outcome is AuditOutcome.SUCCESS
    assert event.campaign_id == UUID(_CAMPAIGN_ID)
    assert event.message_id == UUID(_EVENT_ID)
    assert event.channel == "email"
    assert event.details == {"provider": "mailpit"}
    assert event.correlation_id == "corr-1"
    assert event.trace_id == "1234567890abcdef1234567890abcdef"


def test_payload_rejects_missing_required_field() -> None:
    """Обязательное поле details не может отсутствовать."""
    payload = _payload()
    del payload["details"]

    with pytest.raises(PydanticValidationError):
        AuditEventPayload.model_validate(payload)


def test_payload_rejects_extra_field() -> None:
    """Лишнее поле нарушает контракт additionalProperties false."""
    payload = _payload()
    payload["unknown"] = "value"

    with pytest.raises(PydanticValidationError):
        AuditEventPayload.model_validate(payload)


def test_payload_rejects_naive_datetime() -> None:
    """Время события обязано содержать часовой пояс."""
    payload = _payload()
    payload["occurred_at"] = "2026-11-22T12:00:00"

    with pytest.raises(PydanticValidationError):
        AuditEventPayload.model_validate(payload)


def test_payload_rejects_unknown_action() -> None:
    """Неизвестное действие не принимается."""
    payload = _payload()
    payload["action"] = "unknown.action"

    with pytest.raises(PydanticValidationError):
        AuditEventPayload.model_validate(payload)


def test_payload_rejects_bad_channel() -> None:
    """Канал обязан соответствовать шаблону контракта."""
    payload = _payload()
    payload["channel"] = "Email!"

    with pytest.raises(PydanticValidationError):
        AuditEventPayload.model_validate(payload)
