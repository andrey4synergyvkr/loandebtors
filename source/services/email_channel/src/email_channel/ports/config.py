"""Порт настроек SMTP-адаптера."""

from typing import Protocol

from email_channel.domain import SmtpConfig


class ChannelConfigRepository(Protocol):
    """Доступ к настройкам канала."""

    async def get(self) -> SmtpConfig | None:
        """Вернуть настройки канала или None, если канал еще не настроен."""
        ...

    async def save(self, config: SmtpConfig) -> None:
        """Создать или обновить настройки канала."""
        ...
