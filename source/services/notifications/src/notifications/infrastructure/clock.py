"""Порт текущего времени в инфраструктуре."""

from datetime import UTC, datetime

from notifications.ports.clock import Clock


class SystemClock(Clock):
    """Часы системного времени UTC."""

    def now(self) -> datetime:
        """Вернуть текущее время UTC с часовым поясом."""
        return datetime.now(UTC)
