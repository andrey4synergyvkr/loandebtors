"""Порт рендеринга email-шаблона."""

from collections.abc import Mapping
from typing import Protocol

from email_channel.domain import EmailAddress, EmailTemplate, RenderedEmail


class EmailRenderer(Protocol):
    """Чистая операция подстановки переменных в шаблон."""

    def render(
        self,
        template: EmailTemplate,
        variables: Mapping[str, str],
        recipient: EmailAddress,
    ) -> RenderedEmail:
        """Отрендерить тему, HTML и текстовую часть."""
        ...
