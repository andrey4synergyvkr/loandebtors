"""Разбор входящих команд Scheduler и политика повторов."""

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from scheduler.adapters.messaging.constants import QueueName, RoutingKey
from scheduler.domain import (
    CampaignCancelled,
    CampaignId,
    CampaignScheduled,
    ScheduleKind,
    ScheduleSpec,
    ValidationError,
)


class ScheduleSpecPayload(BaseModel):
    """Расписание в формате AsyncAPI.

    Attributes:
        kind: Вид расписания.
        timezone: Часовой пояс IANA.
        run_at: Время разового запуска.
        cron: Выражение cron.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ScheduleKind
    timezone: str
    run_at: datetime | None = None
    cron: str | None = None


class CampaignScheduledPayload(BaseModel):
    """Тело события campaign.scheduled.

    Attributes:
        campaign_id: Идентификатор кампании.
        schedule: Правило запуска.
        occurred_at: Время события.
    """

    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    schedule: ScheduleSpecPayload
    occurred_at: datetime


class CampaignCancelledPayload(BaseModel):
    """Тело события campaign.cancelled.

    Attributes:
        campaign_id: Идентификатор кампании.
        occurred_at: Время события.
    """

    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    occurred_at: datetime


def parse_command(routing_key: str, body: bytes) -> CampaignScheduled | CampaignCancelled:
    """Разобрать сообщение очереди scheduler.commands.

    Raises:
        ValidationError: Routing key или тело сообщения недопустимы.
    """
    if routing_key == QueueName.SCHEDULER_COMMANDS.value:
        return _parse_from_retry_queue(body)
    if routing_key == RoutingKey.CAMPAIGN_SCHEDULED.value:
        return _parse_scheduled(body)
    if routing_key == RoutingKey.CAMPAIGN_CANCELLED.value:
        return _parse_cancelled(body)
    raise ValidationError(f"Неизвестный routing key планировщика: {routing_key}")


def _parse_from_retry_queue(body: bytes) -> CampaignScheduled | CampaignCancelled:
    """Определить тип события по телу после прохождения retry-очереди."""
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Некорректное тело сообщения: {exc}") from exc
    if isinstance(value, dict) and "schedule" in value:
        return _parse_scheduled(body)
    return _parse_cancelled(body)


def _parse_scheduled(body: bytes) -> CampaignScheduled:
    """Разобрать campaign.scheduled."""
    scheduled_payload = _validate(CampaignScheduledPayload, body)
    return CampaignScheduled(
        campaign_id=CampaignId(scheduled_payload.campaign_id),
        schedule=ScheduleSpec(
            kind=scheduled_payload.schedule.kind,
            timezone=scheduled_payload.schedule.timezone,
            run_at=scheduled_payload.schedule.run_at,
            cron=scheduled_payload.schedule.cron,
        ),
        occurred_at=_require_timezone(scheduled_payload.occurred_at, "occurred_at"),
    )


def _parse_cancelled(body: bytes) -> CampaignCancelled:
    """Разобрать campaign.cancelled."""
    cancelled_payload = _validate(CampaignCancelledPayload, body)
    return CampaignCancelled(
        campaign_id=CampaignId(cancelled_payload.campaign_id),
        occurred_at=_require_timezone(cancelled_payload.occurred_at, "occurred_at"),
    )


def retry_attempts(headers: Mapping[str, Any]) -> int:
    """Вернуть число прохождений сообщения через retry-очередь."""
    deaths = headers.get("x-death")
    if not isinstance(deaths, list):
        return 0
    attempts = 0
    for death in deaths:
        if not isinstance(death, Mapping):
            continue
        if death.get("queue") != f"{QueueName.SCHEDULER_COMMANDS.value}.retry":
            continue
        count = death.get("count")
        if isinstance(count, int):
            attempts += count
    return attempts


def should_dead_letter(headers: Mapping[str, Any], max_attempts: int) -> bool:
    """Решить, исчерпаны ли повторы обработки сообщения."""
    return retry_attempts(headers) >= max_attempts


def decode_for_dead_letter(body: bytes) -> dict[str, object]:
    """Подготовить тело сообщения для dead-letter очереди."""
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": body.decode("utf-8", "replace")}
    if isinstance(value, dict):
        return value
    return {"value": value}


def _validate[PayloadT: BaseModel](model: type[PayloadT], body: bytes) -> PayloadT:
    """Разобрать JSON-тело и проверить обязательные поля."""
    try:
        return model.model_validate_json(body)
    except ValueError as exc:
        raise ValidationError(f"Некорректное тело сообщения: {exc}") from exc


def _require_timezone(value: datetime, field: str) -> datetime:
    """Проверить, что время содержит часовой пояс."""
    if value.tzinfo is None:
        raise ValidationError(f"{field} должен содержать часовой пояс")
    return value
