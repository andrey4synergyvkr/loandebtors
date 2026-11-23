"""Перечисления домена Scheduler."""

from enum import StrEnum


class ScheduleStatus(StrEnum):
    """Состояние расписания кампании.

    Attributes:
        ACTIVE: Задание зарегистрировано и будет запущено.
        PAUSED: Задание временно не запускается.
        CANCELLED: Задание снято, кампания отменена.
        COMPLETED: Разовое задание выполнено.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
