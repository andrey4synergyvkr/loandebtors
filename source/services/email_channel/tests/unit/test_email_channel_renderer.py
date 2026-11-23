"""Проверка рендеринга email-шаблонов."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from email_channel.adapters.smtp.renderer import Jinja2EmailRenderer
from email_channel.domain import EmailAddress, EmailTemplate, TemplateError, TemplateKey

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _template() -> EmailTemplate:
    return EmailTemplate(
        key=TemplateKey("payment-reminder"),
        version=1,
        locale="ru-RU",
        subject_template="Напоминание {{ name }}",
        html_template="<p>Здравствуйте, {{ name }}</p>",
        plain_text_template="Здравствуйте, {{ name }}",
        required_variables=("name",),
        updated_at=_NOW,
    )


def test_renderer_substitutes_variables_and_escapes_html() -> None:
    """HTML экранируется, тема и текст остаются строками."""
    rendered = Jinja2EmailRenderer().render(
        _template(),
        {"name": "<b>Иван</b>"},
        EmailAddress("debtor@example.com"),
    )

    assert rendered.recipient == "debtor@example.com"
    assert rendered.subject == "Напоминание <b>Иван</b>"
    assert rendered.plain_text_body == "Здравствуйте, <b>Иван</b>"
    assert rendered.html_body == "<p>Здравствуйте, &lt;b&gt;Иван&lt;/b&gt;</p>"


def test_renderer_rejects_missing_required_variable() -> None:
    """Отсутствие обязательной переменной даёт TemplateError."""
    with pytest.raises(TemplateError):
        Jinja2EmailRenderer().render(
            _template(),
            {},
            EmailAddress("debtor@example.com"),
        )


def test_renderer_wraps_jinja_error() -> None:
    """Синтаксическая ошибка Jinja2 превращается в TemplateError."""
    template = _template()
    broken = EmailTemplate(
        key=template.key,
        version=template.version,
        locale=template.locale,
        subject_template="{{ name ",
        html_template=template.html_template,
        plain_text_template=template.plain_text_template,
        required_variables=template.required_variables,
        updated_at=template.updated_at,
    )

    with pytest.raises(TemplateError):
        Jinja2EmailRenderer().render(
            broken,
            {"name": "Иван"},
            EmailAddress("debtor@example.com"),
        )


def test_renderer_generates_unique_recipient() -> None:
    """Получатель не зависит от переменных шаблона."""
    rendered = Jinja2EmailRenderer().render(
        _template(),
        {"name": str(uuid4())},
        EmailAddress("other@example.com"),
    )

    assert rendered.recipient == "other@example.com"
