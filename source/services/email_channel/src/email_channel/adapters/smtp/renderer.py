"""Рендеринг email-шаблонов на Jinja2."""

from collections.abc import Mapping

from jinja2 import Environment, StrictUndefined, select_autoescape
from jinja2 import TemplateError as JinjaTemplateError

from email_channel.domain import (
    EmailAddress,
    EmailTemplate,
    RenderedEmail,
    TemplateError,
)


class Jinja2EmailRenderer:
    """Подставляет переменные в тему, HTML и текстовую часть."""

    def __init__(self) -> None:
        """Создать окружения Jinja2 для HTML и текста."""
        self._html = Environment(
            autoescape=select_autoescape(enabled_extensions=("html", "xml")),
            undefined=StrictUndefined,
        )
        self._text = Environment(autoescape=False, undefined=StrictUndefined)

    def render(
        self,
        template: EmailTemplate,
        variables: Mapping[str, str],
        recipient: EmailAddress,
    ) -> RenderedEmail:
        """Отрендерить письмо или выбросить TemplateError."""
        missing = [name for name in template.required_variables if name not in variables]
        if missing:
            raise TemplateError(f"Не заданы переменные шаблона: {', '.join(sorted(missing))}")
        try:
            subject = self._text.from_string(template.subject_template).render(**variables)
            html_body = self._html.from_string(template.html_template).render(**variables)
            plain_text = self._text.from_string(template.plain_text_template).render(**variables)
        except JinjaTemplateError as exc:
            raise TemplateError(f"Ошибка рендеринга шаблона: {type(exc).__name__}") from exc
        return RenderedEmail(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            plain_text_body=plain_text,
        )
