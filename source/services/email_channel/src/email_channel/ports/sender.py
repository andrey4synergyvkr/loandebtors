"""Порты отправки письма и получения секрета."""

from typing import Protocol

from email_channel.domain import RenderedEmail, SecretRef, SendResult, SmtpConfig


class EmailSender(Protocol):
    """Отправка готового письма через SMTP-провайдера."""

    async def send(
        self,
        config: SmtpConfig,
        email: RenderedEmail,
        password: str,
    ) -> SendResult:
        """Отправить письмо и вернуть результат с классификацией ошибки."""
        ...


class SecretsProvider(Protocol):
    """Получение значения секрета по ссылке."""

    async def get(self, ref: SecretRef) -> str:
        """Вернуть значение секрета."""
        ...
