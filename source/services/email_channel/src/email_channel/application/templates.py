"""Сценарии email-шаблонов."""

from dataclasses import dataclass
from datetime import datetime
from re import fullmatch
from uuid import uuid4

from email_channel.application.config import RequestContext
from email_channel.domain import (
    EMAIL_CHANNEL_SERVICE,
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditOutcome,
    Channel,
    EmailTemplate,
    NotFoundError,
    TemplateKey,
    ValidationError,
)
from email_channel.ports.clock import Clock
from email_channel.ports.uow import UnitOfWorkFactory

TEMPLATE_KEY_PATTERN = r"^[a-z][a-z0-9._-]*$"
LOCALE_PATTERN = r"^[a-z]{2}(-[A-Z]{2})?$"
VARIABLE_PATTERN = r"^[a-z][a-z0-9_]*$"
MAX_TEMPLATE_KEY_LENGTH = 100
MAX_LOCALE_LENGTH = 10
MAX_VARIABLE_LENGTH = 100
EMAIL_TEMPLATE_ENTITY_TYPE = "email_template"


@dataclass(frozen=True, slots=True)
class UpsertEmailTemplateCommand:
    """Параметры сохранения email-шаблона.

    Attributes:
        key: Логический ключ шаблона.
        version: Версия канального варианта.
        locale: Язык и регион.
        subject_template: Jinja2-шаблон темы.
        html_template: Jinja2-шаблон HTML-части.
        plain_text_template: Jinja2-шаблон текстовой части.
        required_variables: Обязательные переменные.
    """

    key: str
    version: int
    locale: str
    subject_template: str
    html_template: str
    plain_text_template: str
    required_variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TemplatePage:
    """Страница email-шаблонов.

    Attributes:
        items: Шаблоны текущей страницы.
        total: Общее число шаблонов.
        limit: Размер страницы.
        offset: Смещение.
    """

    items: tuple[EmailTemplate, ...]
    total: int
    limit: int
    offset: int


class EmailTemplateService:
    """Читает и сохраняет email-варианты шаблонов."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        """Сохранить фабрику единиц работы и часы."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def list_templates(
        self,
        key: TemplateKey | None,
        locale: str | None,
        limit: int,
        offset: int,
    ) -> TemplatePage:
        """Вернуть страницу email-шаблонов."""
        async with self._uow_factory() as uow:
            items, total = await uow.templates.list(key, locale, limit, offset)
        return TemplatePage(
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_template(
        self,
        key: TemplateKey,
        version: int,
        locale: str | None = None,
    ) -> EmailTemplate:
        """Вернуть шаблон или ошибку NotFoundError."""
        async with self._uow_factory() as uow:
            template = await uow.templates.get(key, version, locale)
        if template is None:
            raise NotFoundError(f"Email-шаблон {key} версии {version} не найден")
        return template

    async def upsert_template(
        self,
        command: UpsertEmailTemplateCommand,
        context: RequestContext,
    ) -> EmailTemplate:
        """Создать или обновить шаблон и записать audit-событие."""
        _validate(command)
        now = self._clock.now()
        template = EmailTemplate(
            key=TemplateKey(command.key),
            version=command.version,
            locale=command.locale,
            subject_template=command.subject_template,
            html_template=command.html_template,
            plain_text_template=command.plain_text_template,
            required_variables=command.required_variables,
            updated_at=now,
        )
        async with self._uow_factory() as uow:
            await uow.templates.save(template)
            await uow.audit.add(_audit_event(template, now, context))
            await uow.commit()
        return template


def _validate(command: UpsertEmailTemplateCommand) -> None:
    """Проверить ключ, локаль, версию и обязательные поля."""
    if fullmatch(TEMPLATE_KEY_PATTERN, command.key) is None:
        raise ValidationError("key не соответствует шаблону")
    if len(command.key) > MAX_TEMPLATE_KEY_LENGTH:
        raise ValidationError("key слишком длинный")
    if command.version < 1:
        raise ValidationError("version должна быть не меньше 1")
    if fullmatch(LOCALE_PATTERN, command.locale) is None:
        raise ValidationError("locale не соответствует шаблону")
    if len(command.locale) > MAX_LOCALE_LENGTH:
        raise ValidationError("locale слишком длинный")
    if not command.subject_template:
        raise ValidationError("subject_template не должен быть пустым")
    if not command.html_template:
        raise ValidationError("html_template не должен быть пустым")
    if not command.plain_text_template:
        raise ValidationError("plain_text_template не должен быть пустым")
    if len(set(command.required_variables)) != len(command.required_variables):
        raise ValidationError("required_variables не должны повторяться")
    for variable in command.required_variables:
        if len(variable) > MAX_VARIABLE_LENGTH:
            raise ValidationError("Имя переменной слишком длинное")
        if fullmatch(VARIABLE_PATTERN, variable) is None:
            raise ValidationError("Имя переменной должно соответствовать шаблону ^[a-z][a-z0-9_]*$")


def _audit_event(
    template: EmailTemplate,
    occurred_at: datetime,
    context: RequestContext,
) -> AuditEvent:
    """Собрать audit-событие изменения email-шаблона."""
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=occurred_at,
        service=EMAIL_CHANNEL_SERVICE,
        actor=AuditActor(type=AuditActorType.ADMINISTRATOR, identifier=None),
        action=AuditAction.CHANNEL_CONFIG_UPDATED,
        entity_type=EMAIL_TEMPLATE_ENTITY_TYPE,
        entity_id=f"{template.key}:{template.version}",
        campaign_id=None,
        message_id=None,
        channel=Channel("email"),
        outcome=AuditOutcome.SUCCESS,
        details={
            "key": template.key,
            "version": str(template.version),
            "locale": template.locale,
            "required_variables": ",".join(template.required_variables),
        },
        correlation_id=context.correlation_id or uuid4().hex,
        trace_id=context.trace_id,
    )
