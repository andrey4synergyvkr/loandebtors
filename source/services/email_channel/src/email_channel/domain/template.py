"""Email-вариант шаблона."""

from dataclasses import dataclass
from datetime import datetime

from email_channel.domain.ids import TemplateKey


@dataclass(frozen=True, slots=True)
class EmailTemplate:
    """Канальный вариант логического шаблона.

    Attributes:
        key: Логический ключ шаблона.
        version: Версия канального варианта.
        locale: Язык и регион, например ru-RU.
        subject_template: Jinja2-шаблон темы.
        html_template: Jinja2-шаблон HTML-части.
        plain_text_template: Jinja2-шаблон текстовой части.
        required_variables: Переменные, обязательные для рендеринга.
        updated_at: Время последнего изменения.
    """

    key: TemplateKey
    version: int
    locale: str
    subject_template: str
    html_template: str
    plain_text_template: str
    required_variables: tuple[str, ...]
    updated_at: datetime
