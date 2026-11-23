"""Значения домена Scheduler."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scheduler.domain.errors import ValidationError

CRON_FIELD_COUNT: int = 5


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

    def __post_init__(self) -> None:
        """Проверить согласованность вида, времени и часового пояса.

        Raises:
            ValidationError: Поля расписания противоречат друг другу.
        """
        _validate_timezone(self.timezone)
        if self.kind is ScheduleKind.ONE_OFF:
            if self.run_at is None:
                raise ValidationError("Для one_off требуется run_at")
            if self.cron is not None:
                raise ValidationError("Для one_off поле cron должно быть пустым")
            if self.run_at.tzinfo is None:
                raise ValidationError("run_at должен содержать часовой пояс")
            return
        if self.cron is None or not self.cron.strip():
            raise ValidationError("Для cron требуется выражение cron")
        if self.run_at is not None:
            raise ValidationError("Для cron поле run_at должно быть пустым")
        fields = self.cron.split()
        if len(fields) != CRON_FIELD_COUNT:
            raise ValidationError(f"Выражение cron должно содержать {CRON_FIELD_COUNT} полей")


def _validate_timezone(value: str) -> None:
    """Проверить, что часовой пояс существует в базе IANA.

    Raises:
        ValidationError: Часовой пояс не найден.
    """
    if not value or not value.strip():
        raise ValidationError("Часовой пояс не задан")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"Неизвестный часовой пояс: {value}") from exc
