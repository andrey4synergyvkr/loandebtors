"""Проверка консьюмера message.send."""

import json
from collections.abc import Mapping
from typing import Any, cast
from uuid import uuid4

from aio_pika.abc import AbstractIncomingMessage

from email_channel.adapters.messaging.connection import RabbitMQConnection
from email_channel.adapters.messaging.constants import EVENTS_EXCHANGE
from email_channel.adapters.messaging.consumer import (
    EMAIL_DLQ_ROUTING_KEY,
    EmailCommandConsumer,
)
from email_channel.application.config import RequestContext
from email_channel.application.delivery import DeliveryResult, DeliveryStatus, EmailDeliveryService
from email_channel.config import Settings
from email_channel.domain import NotificationCommand
from email_channel.infrastructure.metrics import Metrics

_EVENT_ID = str(uuid4())
_CAMPAIGN_ID = str(uuid4())


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
    """Публикатор DLQ."""

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


class FakeDelivery:
    """Сценарий отправки с заданным результатом."""

    def __init__(self) -> None:
        """Создать пустой список команд."""
        self.commands: list[NotificationCommand] = []
        self.failures: list[tuple[NotificationCommand, str, str]] = []
        self.error: Exception | None = None
        self.result = DeliveryResult(status=DeliveryStatus.SENT, attempt_number=1)

    async def handle(
        self,
        command: NotificationCommand,
        context: RequestContext,
    ) -> DeliveryResult:
        """Запомнить команду и вернуть результат."""
        if self.error is not None:
            raise self.error
        self.commands.append(command)
        return self.result

    async def record_consumer_failure(
        self,
        command: NotificationCommand,
        context: RequestContext,
        error_code: str,
        error_message: str,
    ) -> DeliveryResult:
        """Запомнить окончательный отказ обработки."""
        self.failures.append((command, error_code, error_message))
        return DeliveryResult(status=DeliveryStatus.FAILED, attempt_number=1)


def _settings() -> Settings:
    return Settings(
        service_name="email_channel",
        otel_enabled=False,
        check_dependencies=False,
        run_background_workers=False,
        rabbitmq_retry_max_attempts=2,
    )


def _consumer(
    publisher: FakePublisher,
    delivery: FakeDelivery,
) -> EmailCommandConsumer:
    return EmailCommandConsumer(
        connection=cast(RabbitMQConnection, object()),
        publisher=cast(Any, publisher),
        delivery=cast(EmailDeliveryService, delivery),
        settings=_settings(),
        metrics=Metrics(),
    )


def _payload() -> dict[str, object]:
    return {
        "message_id": _EVENT_ID,
        "campaign_id": _CAMPAIGN_ID,
        "debtor_id": "ABS-100500",
        "channel": "email",
        "template_key": "payment-reminder",
        "template_version": 1,
        "variables": {"name": "Иван"},
        "recipient": {"channel": "email", "address": "debtor@example.com"},
        "idempotency_key": f"{_CAMPAIGN_ID}:ABS-100500:email",
    }


def _payload_bytes() -> bytes:
    return json.dumps(_payload()).encode("utf-8")


async def test_valid_message_is_acked_and_delivered() -> None:
    """Валидная команда передаётся в сценарий и подтверждается."""
    publisher = FakePublisher()
    delivery = FakeDelivery()
    message = FakeMessage(_payload_bytes())

    await _consumer(publisher, delivery).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert message.nacked is False
    assert publisher.calls == []
    assert len(delivery.commands) == 1
    assert str(delivery.commands[0].message_id) == _EVENT_ID


async def test_invalid_json_is_sent_to_dlq() -> None:
    """Битое тело уходит в DLQ и не блокирует очередь."""
    publisher = FakePublisher()
    delivery = FakeDelivery()
    message = FakeMessage(b"not-json")

    await _consumer(publisher, delivery).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert delivery.commands == []
    assert len(publisher.calls) == 1
    assert publisher.calls[0][0] == EVENTS_EXCHANGE
    assert publisher.calls[0][1] == EMAIL_DLQ_ROUTING_KEY


async def test_invalid_payload_is_sent_to_dlq() -> None:
    """Неверная схема команды уходит в DLQ."""
    publisher = FakePublisher()
    delivery = FakeDelivery()
    payload = _payload()
    payload["unknown"] = "value"
    message = FakeMessage(json.dumps(payload).encode("utf-8"))

    await _consumer(publisher, delivery).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert delivery.commands == []
    assert len(publisher.calls) == 1


async def test_non_email_channel_is_sent_to_dlq() -> None:
    """Команда чужого канала не обрабатывается email-сервисом."""
    publisher = FakePublisher()
    delivery = FakeDelivery()
    payload = _payload()
    payload["channel"] = "sms"
    message = FakeMessage(json.dumps(payload).encode("utf-8"))

    await _consumer(publisher, delivery).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert delivery.commands == []
    assert len(publisher.calls) == 1


async def test_delivery_error_is_nacked_for_retry() -> None:
    """Ошибка сценария возвращает сообщение в retry-очередь."""
    publisher = FakePublisher()
    delivery = FakeDelivery()
    delivery.error = RuntimeError("database is down")
    message = FakeMessage(_payload_bytes())

    await _consumer(publisher, delivery).handle(cast(AbstractIncomingMessage, message))

    assert message.nacked is True
    assert message.requeue is False
    assert message.acked is False
    assert publisher.calls == []


async def test_exhausted_retries_are_sent_to_dlq() -> None:
    """После предела попыток сообщение уходит в DLQ."""
    publisher = FakePublisher()
    delivery = FakeDelivery()
    delivery.error = RuntimeError("database is down")
    message = FakeMessage(
        _payload_bytes(),
        {"x-death": [{"queue": "email.commands", "count": 2, "reason": "rejected"}]},
    )

    await _consumer(publisher, delivery).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert publisher.calls[0][1] == EMAIL_DLQ_ROUTING_KEY
    assert len(delivery.failures) == 1
    assert delivery.failures[0][1] == "consumer_retry_exhausted"


async def test_duplicate_status_is_acked() -> None:
    """Повторная команда подтверждается без повторной отправки."""
    publisher = FakePublisher()
    delivery = FakeDelivery()
    delivery.result = DeliveryResult(
        status=DeliveryStatus.DUPLICATE,
        attempt_number=0,
    )
    message = FakeMessage(_payload_bytes())

    await _consumer(publisher, delivery).handle(cast(AbstractIncomingMessage, message))

    assert message.acked is True
    assert publisher.calls == []
