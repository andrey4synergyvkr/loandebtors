"""Значения домена Notifications."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from re import fullmatch
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from notifications.domain.errors import ValidationError
from notifications.domain.ids import Channel

CRON_FIELD_PATTERN: Final = r"^[0-9*/,\-]+$"
CRON_FIELD_COUNT: Final = 5


@dataclass(frozen=True, slots=True)
class Money:
    """Денежная сумма в валюте ISO 4217.

    Attributes:
        amount: Сумма в основных единицах валюты.
        currency: Код валюты ISO 4217, например RUB.
    """

    amount: Decimal
    currency: str


class ScheduleKind(StrEnum):
    """Вид расписания кампании.

    Attributes:
        ONE_OFF: Разовый запуск в момент run_at.
        CRON: Повторяющийся запуск по выражению cron.
    """

    ONE_OFF = "one_off"
    CRON = "cron"


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    """Правило запуска кампании.

    Attributes:
        kind: Вид расписания.
        timezone: Часовой пояс IANA, например Europe/Moscow.
        run_at: Заполняется только для one_off.
        cron: Заполняется только для cron.
    """

    kind: ScheduleKind
    timezone: str
    run_at: datetime | None = None
    cron: str | None = None


def validate_schedule(schedule: ScheduleSpec, now: datetime) -> ScheduleSpec:
    """Проверить правило запуска и вернуть нормализованное значение.

    Raises:
        ValidationError: Часовой пояс, время или cron-выражение недопустимы.
    """
    timezone = schedule.timezone.strip()
    if not timezone:
        raise ValidationError("Часовой пояс расписания не может быть пустым")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"Неизвестный часовой пояс {timezone}") from exc
    if schedule.kind is ScheduleKind.ONE_OFF:
        if schedule.run_at is None:
            raise ValidationError("Для разового запуска нужно указать run_at")
        if schedule.run_at.tzinfo is None:
            raise ValidationError("run_at должен содержать часовой пояс")
        if schedule.run_at <= now:
            raise ValidationError("run_at должен быть позже текущего времени")
        if schedule.cron is not None:
            raise ValidationError("Для разового запуска cron не задается")
        return ScheduleSpec(
            kind=schedule.kind,
            timezone=timezone,
            run_at=schedule.run_at,
        )
    cron = (schedule.cron or "").strip()
    if not cron:
        raise ValidationError("Для cron-расписания нужно указать выражение cron")
    if schedule.run_at is not None:
        raise ValidationError("Для cron-расписания run_at не задается")
    fields = cron.split()
    if len(fields) != CRON_FIELD_COUNT:
        raise ValidationError(f"Выражение cron должно содержать {CRON_FIELD_COUNT} полей")
    for field in fields:
        if fullmatch(CRON_FIELD_PATTERN, field) is None:
            raise ValidationError(f"Поле cron {field} содержит недопустимые символы")
    return ScheduleSpec(
        kind=schedule.kind,
        timezone=timezone,
        cron=cron,
    )


class DeliveryOutcome(StrEnum):
    """Результат попытки доставки.

    Attributes:
        SENT: Провайдер принял сообщение, доставка не подтверждена.
        TRANSIENT_FAILURE: Временная ошибка, попытку можно повторить.
        PERMANENT_FAILURE: Постоянная ошибка, повторы бессмысленны.
        RATE_LIMITED: Провайдер ограничил скорость, нужна пауза.
    """

    SENT = "sent"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True, slots=True)
class Recipient:
    """Получатель сообщения в формате канала.

    Attributes:
        channel: Канал, который должен доставить сообщение.
        address: Адрес в формате канала, для email это почтовый ящик.
    """

    channel: Channel
    address: str
