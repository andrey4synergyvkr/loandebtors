"""Проверка обработчика audit.event."""

import json
from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from aio_pika.abc import AbstractIncomingMessage

from audit_exporter.adapters.messaging.connection import RabbitMQConnection
from audit_exporter.adapters.messaging.constants import AUDIT_DLQ_ROUTING_KEY, EVENTS_EXCHANGE
from audit_exporter.adapters.messaging.consumer import AuditEventConsumer
from audit_exporter.application.audit_ingest import AuditIngestService
from audit_exporter.config import Settings
from audit_exporter.domain import AuditEvent, ConflictError
from audit_exporter.infrastructure.metrics import Metrics

_EVENT_ID = "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"
_CAMPAIGN_ID = "5a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


class FakeMessage:
    """Входящее сообщение с фиксацией ack и nack."""

    def __init__(self, body: bytes, headers: dict[str, Any] | None = None) -> None:
        """Сохранить тело и заголовки."""
        self.body = body
        self.headers = headers
        self.acked = False
        self.nacked = False
        self.requeue: bool | None = None

    async def ack(self) -> None:
        """Зафиксировать подтверждение."""
        self.acked = True

    async def nack(self, requeue: bool = True) -> None:
        """Зафиксировать отклонение."""
        self.nacked = True
        self.requeue = requeue


class FakePublisher:
    """Публикатор, который запоминает вызовы."""

    def __init__(self) -> None:
        """Создать пустой список вызовов."""
        self.calls: list[tuple[str, str, bytes, Mapping[str, str]]] = []
        self.fail = False

    async def publish_raw(
        self,
        exchange: str,
        routing_key: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> None:
        """Запомнить публикацию или выбросить ошибку."""
        if self.fail:
            raise RuntimeError("publish failed")
        self.calls.append((exchange, routing_key, body, headers))


class FakeIngest:
    """Приёмник событий с управляемой ошибкой."""

    def __init__(self) -> None:
        """Создать пустой список событий."""
        self.events: list[AuditEvent] = []
        self.error: Exception | None = None

    async def handle(self, event: AuditEvent) -> None:
        """Запомнить событие или выбросить ошибку."""
        if self.error is not None:
            raise self.error
        self.events.append(event)


class FakeConnection:
    """Заглушка подключения, обработчику она не нужна."""


def _settings() -> Settings:
    return Settings(
        service_name="audit_exporter",
        otel_enabled=False,
        check_dependencies=False,
        run_background_workers=False,
        rabbitmq_retry_max_attempts=2,
    )


def _consumer(
    publisher: FakePublisher,
    ingest: FakeIngest,
) -> AuditEventConsumer:
    connection = cast(RabbitMQConnection, FakeConnection())
    return AuditEventConsumer(connection, publisher, cast(AuditIngestService, ingest), _settings(), Metrics())


def _payload() -> dict[str, object]:
    return {
        "event_id": _EVENT_ID,
        "occurred_at": "2026-11-22T12:00:00Z",
        "service": "email_channel",
        "actor": {"type": "system", "identifier": "email_channel"},
        "action": "message.sent",
        "entity_type": "message",
        "entity_id": _EVENT_ID,
        "campaign_id": _CAMPAIGN_ID,
        "message_id": _EVENT_ID,
        "channel": "email",
        "outcome": "success",
        "details": {"provider": "mailpit"},
        "correlation_id": "corr-1",
        "trace_id": None,
    }


def _payload_bytes() -> bytes:
    return json.dumps(_payload()).encode("utf-8")


async def test_valid_message_is_acked_and_ingested() -> None:
    """Валидное сообщение пишется в журнал и подтверждается."""
    publisher = FakePublisher()
    ingest = FakeIngest()
    message = FakeMessage(_payload_bytes())

    await _consumer(publisher, ingest).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert message.nacked is False
    assert publisher.calls == []
    assert len(ingest.events) == 1
    assert ingest.events[0].event_id == UUID(_EVENT_ID)


async def test_invalid_json_is_sent_to_dlq() -> None:
    """Битое тело не блокирует очередь и уходит в DLQ."""
    publisher = FakePublisher()
    ingest = FakeIngest()
    message = FakeMessage(b"not-json")

    await _consumer(publisher, ingest).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert ingest.events == []
    assert len(publisher.calls) == 1
    exchange, routing_key, body, headers = publisher.calls[0]
    assert exchange == EVENTS_EXCHANGE
    assert routing_key == AUDIT_DLQ_ROUTING_KEY
    assert body == b"not-json"
    assert "x-error" in headers


async def test_unknown_action_is_sent_to_dlq() -> None:
    """Неизвестное действие не пишется в журнал."""
    publisher = FakePublisher()
    ingest = FakeIngest()
    payload = _payload()
    payload["action"] = "unknown.action"
    message = FakeMessage(json.dumps(payload).encode("utf-8"))

    await _consumer(publisher, ingest).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert ingest.events == []
    assert len(publisher.calls) == 1


async def test_conflict_is_sent_to_dlq() -> None:
    """Событие с конфликтом event_id уходит в DLQ, а не повторяется бесконечно."""
    publisher = FakePublisher()
    ingest = FakeIngest()
    ingest.error = ConflictError("событие уже записано с другим содержимым")
    message = FakeMessage(_payload_bytes())

    await _consumer(publisher, ingest).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert message.nacked is False
    assert len(publisher.calls) == 1
    assert publisher.calls[0][1] == AUDIT_DLQ_ROUTING_KEY


async def test_transient_error_is_nacked_for_retry() -> None:
    """Временная ошибка возвращает сообщение в retry-очередь."""
    publisher = FakePublisher()
    ingest = FakeIngest()
    ingest.error = RuntimeError("database is down")
    message = FakeMessage(_payload_bytes())

    await _consumer(publisher, ingest).handle(cast(AbstractIncomingMessage, message))

    assert message.nacked is True
    assert message.requeue is False
    assert message.acked is False
    assert publisher.calls == []


async def test_exhausted_retries_are_sent_to_dlq() -> None:
    """После предела попыток сообщение уходит в DLQ."""
    publisher = FakePublisher()
    ingest = FakeIngest()
    ingest.error = RuntimeError("database is down")
    message = FakeMessage(
        _payload_bytes(),
        {"x-death": [{"queue": "audit.events", "count": 2, "reason": "rejected"}]},
    )

    await _consumer(publisher, ingest).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert publisher.calls[0][1] == AUDIT_DLQ_ROUTING_KEY


async def test_dlq_publish_failure_nacks_for_retry() -> None:
    """Если DLQ недоступен, сообщение остаётся в retry-цикле."""
    publisher = FakePublisher()
    publisher.fail = True
    ingest = FakeIngest()
    message = FakeMessage(b"not-json")

    await _consumer(publisher, ingest).handle(cast(AbstractIncomingMessage, message))

    assert message.nacked is True
    assert message.requeue is False
    assert message.acked is False


def test_retry_count_sums_audit_queue_deaths() -> None:
    """Счётчик попыток учитывает только dead-letter переходы audit.events."""
    headers = {
        "x-death": [
            {"queue": "audit.events", "count": 2, "reason": "rejected"},
            {"queue": "other.queue", "count": 5, "reason": "rejected"},
            {"queue": "audit.events", "count": 1, "reason": "expired"},
        ]
    }

    assert AuditEventConsumer._retry_count(headers) == 3


def test_retry_count_without_header_is_zero() -> None:
    """Без x-death сообщение считается первой попыткой."""
    assert AuditEventConsumer._retry_count({}) == 0
    assert AuditEventConsumer._retry_count({"x-death": "bad"}) == 0
