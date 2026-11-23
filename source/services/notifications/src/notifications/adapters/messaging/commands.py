"""Разбор входящих команд Notifications и политика повторов."""

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from notifications.adapters.messaging.constants import QueueName, RoutingKey
from notifications.domain import (
    CampaignId,
    CampaignStart,
    Channel,
    DeliveryOutcome,
    MessageFailed,
    MessageId,
    MessageSent,
    ValidationError,
)


class CampaignStartPayload(BaseModel):
    """Тело команды campaign.start.

    Attributes:
        campaign_id: Идентификатор кампании.
        scheduled_for: Плановое время запуска.
        occurred_at: Время публикации события.
    """

    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    scheduled_for: datetime
    occurred_at: datetime


class MessageSentPayload(BaseModel):
    """Тело события message.sent.

    Attributes:
        message_id: Идентификатор сообщения.
        campaign_id: Идентификатор кампании.
        channel: Канал доставки.
        attempt_number: Номер попытки.
        provider_message_id: Идентификатор письма провайдера.
        occurred_at: Время результата.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    campaign_id: UUID
    channel: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    attempt_number: int = Field(ge=1)
    provider_message_id: str | None = None
    occurred_at: datetime


class MessageFailedPayload(BaseModel):
    """Тело события message.failed.

    Attributes:
        message_id: Идентификатор сообщения.
        campaign_id: Идентификатор кампании.
        channel: Канал доставки.
        attempt_number: Номер попытки.
        outcome: Классификация ошибки.
        retryable: Признак возможности повтора.
        error_code: Код ошибки провайдера.
        error_message: Описание ошибки.
        occurred_at: Время результата.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    campaign_id: UUID
    channel: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    attempt_number: int = Field(ge=1)
    outcome: DeliveryOutcome
    retryable: bool
    error_code: str | None = None
    error_message: str | None = None
    occurred_at: datetime


def parse_start_command(routing_key: str, body: bytes) -> CampaignStart:
    """Разобрать сообщение очереди notification.commands.

    Raises:
        ValidationError: Routing key или тело сообщения недопустимы.
    """
    # После retry-очереди RabbitMQ возвращает сообщение с routing key очереди,
    # поэтому campaign.start принимается и под этим ключом.
    if routing_key not in (
        RoutingKey.CAMPAIGN_START.value,
        QueueName.NOTIFICATION_COMMANDS.value,
    ):
        raise ValidationError(f"Неизвестный routing key Notifications: {routing_key}")
    try:
        payload = CampaignStartPayload.model_validate_json(body)
    except ValueError as exc:
        raise ValidationError(f"Некорректное тело campaign.start: {exc}") from exc
    return CampaignStart(
        campaign_id=CampaignId(payload.campaign_id),
        scheduled_for=_require_timezone(payload.scheduled_for, "scheduled_for"),
        occurred_at=_require_timezone(payload.occurred_at, "occurred_at"),
    )


def parse_result_command(routing_key: str, body: bytes) -> MessageSent | MessageFailed:
    """Разобрать сообщение очереди notification.results.

    Raises:
        ValidationError: Routing key или тело сообщения недопустимы.
    """
    if routing_key == RoutingKey.MESSAGE_SENT.value:
        return _parse_sent(body)
    if routing_key == RoutingKey.MESSAGE_FAILED.value:
        return _parse_failed(body)
    # После retry-очереди routing key теряется, тип определяется по телу.
    if routing_key == QueueName.NOTIFICATION_RESULTS.value:
        try:
            data = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Некорректное тело результата: {exc}") from exc
        if isinstance(data, dict) and "outcome" in data:
            return _parse_failed(body)
        return _parse_sent(body)
    raise ValidationError(f"Неизвестный routing key результатов: {routing_key}")


def _parse_sent(body: bytes) -> MessageSent:
    """Разобрать message.sent."""
    try:
        payload = MessageSentPayload.model_validate_json(body)
    except ValueError as exc:
        raise ValidationError(f"Некорректное тело message.sent: {exc}") from exc
    return MessageSent(
        message_id=MessageId(payload.message_id),
        campaign_id=CampaignId(payload.campaign_id),
        channel=Channel(payload.channel),
        attempt_number=payload.attempt_number,
        provider_message_id=payload.provider_message_id,
        occurred_at=_require_timezone(payload.occurred_at, "occurred_at"),
    )


def _parse_failed(body: bytes) -> MessageFailed:
    """Разобрать message.failed."""
    try:
        payload = MessageFailedPayload.model_validate_json(body)
    except ValueError as exc:
        raise ValidationError(f"Некорректное тело message.failed: {exc}") from exc
    if payload.outcome is DeliveryOutcome.SENT:
        raise ValidationError("message.failed не может содержать outcome=sent")
    if payload.attempt_number < 1:
        raise ValidationError("attempt_number должен быть не меньше 1")
    return MessageFailed(
        message_id=MessageId(payload.message_id),
        campaign_id=CampaignId(payload.campaign_id),
        channel=Channel(payload.channel),
        attempt_number=payload.attempt_number,
        outcome=payload.outcome,
        retryable=payload.retryable,
        error_code=payload.error_code,
        error_message=payload.error_message,
        occurred_at=_require_timezone(payload.occurred_at, "occurred_at"),
    )


def retry_attempts(headers: Mapping[str, Any], queue_name: str) -> int:
    """Вернуть число прохождений сообщения через retry-очередь.

    Args:
        headers: Заголовки входящего сообщения.
        queue_name: Основная очередь, у которой считается retry-очередь.
    """
    deaths = headers.get("x-death")
    if not isinstance(deaths, list):
        return 0
    retry_queue_name = f"{queue_name}.retry"
    attempts = 0
    for death in deaths:
        if not isinstance(death, Mapping):
            continue
        if death.get("queue") != retry_queue_name:
            continue
        count = death.get("count")
        if isinstance(count, int) and not isinstance(count, bool):
            attempts += count
    return attempts


def should_dead_letter(
    headers: Mapping[str, Any],
    max_attempts: int,
    queue_name: str,
) -> bool:
    """Решить, исчерпаны ли повторы обработки сообщения."""
    return retry_attempts(headers, queue_name) >= max_attempts


def decode_for_dead_letter(body: bytes) -> dict[str, object]:
    """Подготовить тело сообщения для dead-letter очереди."""
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": body.decode("utf-8", "replace")}
    if isinstance(value, dict):
        return value
    return {"value": value}


def _require_timezone(value: datetime, field: str) -> datetime:
    """Проверить, что время содержит часовой пояс."""
    if value.tzinfo is None:
        raise ValidationError(f"{field} должен содержать часовой пояс")
    return value
