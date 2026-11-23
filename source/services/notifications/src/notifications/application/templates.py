"""Сценарии управления логическими шаблонами."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import uuid4

from notifications.application.common import RequestContext, validate_page
from notifications.domain import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditOutcome,
    ConflictError,
    NotFoundError,
    NotificationTemplate,
    TemplateKey,
    TemplateStatus,
    ValidationError,
    create_template,
)
from notifications.ports.clock import Clock
from notifications.ports.uow import UnitOfWorkFactory

NOTIFICATIONS_SERVICE: Final = "notifications"
TEMPLATE_ENTITY_TYPE: Final = "template"


@dataclass(frozen=True, slots=True)
class CreateTemplateCommand:
    """Параметры создания версии шаблона.

    Attributes:
        key: Логический ключ шаблона.
        version: Номер версии.
        description: Назначение шаблона.
        required_variables: Обязательные переменные рендеринга.
    """

    key: str
    version: int
    description: str
    required_variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TemplatePage:
    """Страница версий шаблонов.

    Attributes:
        items: Версии текущей страницы.
        total: Общее число версий с учётом фильтра.
        limit: Запрошенный размер страницы.
        offset: Запрошенное смещение.
    """

    items: Sequence[NotificationTemplate]
    total: int
    limit: int
    offset: int


class TemplateService:
    """Управляет версиями логических шаблонов и пишет аудит."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        """Сохранить фабрику единиц работы и часы."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def list_templates(
        self,
        *,
        status: TemplateStatus | None,
        limit: int,
        offset: int,
    ) -> TemplatePage:
        """Вернуть страницу версий шаблонов.

        Raises:
            ValidationError: Размер страницы или смещение недопустимы.
        """
        validate_page(limit, offset)
        async with self._uow_factory() as uow:
            items = await uow.templates.list(status=status, limit=limit, offset=offset)
            total = await uow.templates.count(status=status)
        return TemplatePage(items=items, total=total, limit=limit, offset=offset)

    async def get_template(
        self,
        key: TemplateKey,
        version: int | None = None,
    ) -> NotificationTemplate:
        """Вернуть версию шаблона или последнюю активную.

        Raises:
            ValidationError: Номер версии недопустим.
            NotFoundError: Шаблон не найден.
        """
        if version is not None and version < 1:
            raise ValidationError("Версия шаблона должна быть не меньше 1")
        async with self._uow_factory() as uow:
            template = await uow.templates.get(key, version)
        if template is None:
            raise NotFoundError(_not_found_message(key, version))
        return template

    async def create_template(
        self,
        command: CreateTemplateCommand,
        context: RequestContext,
    ) -> NotificationTemplate:
        """Создать версию шаблона в статусе draft.

        Raises:
            ValidationError: Поля шаблона недопустимы.
            ConflictError: Версия с таким ключом уже существует.
        """
        now = self._clock.now()
        template = create_template(
            key=command.key,
            version=command.version,
            description=command.description,
            required_variables=command.required_variables,
            now=now,
        )
        async with self._uow_factory() as uow:
            existing = await uow.templates.get(template.key, template.version)
            if existing is not None:
                raise ConflictError(f"Версия {template.version} шаблона {template.key} уже существует")
            await uow.templates.save(template)
            await uow.audit.add(
                _audit_event(
                    action=AuditAction.TEMPLATE_CREATED,
                    template=template,
                    details={
                        "key": template.key,
                        "version": str(template.version),
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()
        return template

    async def update_status(
        self,
        key: TemplateKey,
        version: int,
        status: TemplateStatus,
        context: RequestContext,
    ) -> NotificationTemplate:
        """Сменить статус версии шаблона и записать аудит.

        Raises:
            NotFoundError: Шаблон не найден.
            InvalidStateError: Переход статуса запрещён.
        """
        if version < 1:
            raise ValidationError("Версия шаблона должна быть не меньше 1")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            template = await uow.templates.get(key, version)
            if template is None:
                raise NotFoundError(_not_found_message(key, version))
            previous_status = template.status
            changed = template.change_status(status, now)
            if not changed:
                return template
            if status is TemplateStatus.ACTIVE:
                await uow.templates.archive_active(
                    key=template.key,
                    except_version=template.version,
                    now=now,
                )
            await uow.templates.save(template)
            await uow.audit.add(
                _audit_event(
                    action=AuditAction.TEMPLATE_STATUS_CHANGED,
                    template=template,
                    details={
                        "key": template.key,
                        "version": str(template.version),
                        "from_status": previous_status.value,
                        "to_status": template.status.value,
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()
        return template


def _not_found_message(key: TemplateKey, version: int | None) -> str:
    """Собрать сообщение об отсутствующем шаблоне."""
    if version is None:
        return f"Активная версия шаблона {key} не найдена"
    return f"Версия {version} шаблона {key} не найдена"


def _audit_event(
    *,
    action: AuditAction,
    template: NotificationTemplate,
    details: dict[str, str],
    now: datetime,
    context: RequestContext,
) -> AuditEvent:
    """Собрать audit-событие шаблона."""
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=now,
        service=NOTIFICATIONS_SERVICE,
        actor=AuditActor(type=AuditActorType.OPERATOR, identifier=None),
        action=action,
        entity_type=TEMPLATE_ENTITY_TYPE,
        entity_id=f"{template.key}:{template.version}",
        campaign_id=None,
        message_id=None,
        channel=None,
        outcome=AuditOutcome.SUCCESS,
        details=details,
        correlation_id=context.correlation_id or uuid4().hex,
        trace_id=context.trace_id,
    )
