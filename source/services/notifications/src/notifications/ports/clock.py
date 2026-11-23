"""Порт текущего времени."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Источник текущего времени UTC."""

    def now(self) -> datetime:
        """Вернуть текущее время UTC, включая часовой пояс."""
        ...
