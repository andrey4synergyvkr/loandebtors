"""Порт проверки доступности SMTP-провайдера."""

from typing import Protocol


class SmtpProbe(Protocol):
    """Проверка TCP-доступности SMTP-хоста."""

    async def check(self, host: str, port: int, timeout_seconds: float) -> str | None:
        """Вернуть None, если хост доступен, или описание ошибки."""
        ...
