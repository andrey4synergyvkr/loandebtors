"""Порт репозитория email-шаблонов."""

from collections.abc import Sequence
from typing import Protocol

from email_channel.domain import EmailTemplate, TemplateKey


class EmailTemplateRepository(Protocol):
    """Доступ к канальным вариантам шаблонов."""

    async def get(
        self,
        key: TemplateKey,
        version: int,
        locale: str | None = None,
    ) -> EmailTemplate | None:
        """Вернуть вариант шаблона или None."""
        ...

    async def list(
        self,
        key: TemplateKey | None = None,
        locale: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[EmailTemplate], int]:
        """Вернуть страницу вариантов и общее число."""
        ...

    async def save(self, template: EmailTemplate) -> None:
        """Создать или обновить вариант шаблона."""
        ...
