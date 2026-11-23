"""Порт ограничения скорости отправки."""

from typing import Protocol


class RateLimiter(Protocol):
    """Глобальный лимит отправки канала."""

    def configure(self, rate_per_second: int) -> None:
        """Применить лимит из настроек канала."""
        ...

    async def acquire(self) -> None:
        """Дождаться свободного слота."""
        ...
