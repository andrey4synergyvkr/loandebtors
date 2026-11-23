"""Получение секретов из переменных окружения."""

import os

from email_channel.config import Settings
from email_channel.domain import SecretError, SecretRef

SMTP_PASSWORD_REF: str = "SMTP_PASSWORD"


class EnvSecretsProvider:
    """Читает секреты из окружения и настроек SMTP."""

    def __init__(self, settings: Settings) -> None:
        """Сохранить настройки сервиса."""
        self._settings = settings

    async def get(self, ref: SecretRef) -> str:
        """Вернуть значение секрета."""
        if ref == SMTP_PASSWORD_REF:
            return self._settings.smtp_password
        value = os.environ.get(ref)
        if value is None:
            raise SecretError(f"Секрет {ref} не найден")
        return value
