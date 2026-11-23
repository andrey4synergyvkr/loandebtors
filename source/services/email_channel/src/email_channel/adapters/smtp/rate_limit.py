"""Глобальный ограничитель скорости Email Channel."""

import asyncio
import time


class AsyncioRateLimiter:
    """Распределяет отправки с заданным минимальным интервалом."""

    def __init__(self, rate_per_second: int) -> None:
        """Сохранить начальный лимит."""
        self._lock = asyncio.Lock()
        self._interval = 0.0
        self._next_allowed = 0.0
        self.configure(rate_per_second)

    def configure(self, rate_per_second: int) -> None:
        """Применить лимит из настроек канала."""
        self._interval = 1.0 / max(1, rate_per_second)

    async def acquire(self) -> None:
        """Дождаться свободного слота."""
        async with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self._interval
        if wait > 0:
            await asyncio.sleep(wait)
