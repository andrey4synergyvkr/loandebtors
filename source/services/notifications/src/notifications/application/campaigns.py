"""Сценарии управления кампаниями до запуска."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
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
    Campaign,
    CampaignCancelled,
    CampaignId,
    CampaignScheduled,
    CampaignStart,
    CampaignStatus,
    Channel,
    ConflictError,
    DebtorSelection,
    InvalidStateError,
    MessageId,
    MessageStatus,
    NotFoundError,
    NotificationMessage,
    NotificationTemplate,
    ScheduleSpec,
    TemplateKey,
    TemplateStatus,
    ValidationError,
    create_campaign,
)
from notifications.ports.clock import Clock
from notifications.ports.uow import UnitOfWork, UnitOfWorkFactory

NOTIFICATIONS_SERVICE: Final = "notifications"
CAMPAIGN_ENTITY_TYPE: Final = "campaign"


@dataclass(frozen=True, slots=True)
class CreateCampaignCommand:
    """Параметры создания кампании.

    Attributes:
        name: Человекочитаемое имя кампании.
        channel: Канал рассылки.
        template_key: Логический ключ шаблона.
        template_version: Версия шаблона.
        selection: Параметры выборки должников.
    """

    name: str
    channel: Channel
    template_key: TemplateKey
    template_version: int
    selection: DebtorSelection


@dataclass(frozen=True, slots=True)
class UpdateCampaignCommand:
    """Изменяемые поля кампании в статусе draft.

    Attributes:
        name: Новое имя или None.
        template_key: Новый ключ шаблона или None.
        template_version: Новая версия шаблона или None.
        selection: Новые критерии выборки или None.
    """

    name: str | None
    template_key: TemplateKey | None
    template_version: int | None
    selection: DebtorSelection | None


@dataclass(frozen=True, slots=True)
class CampaignPage:
    """Страница кампаний.

    Attributes:
        items: Кампании текущей страницы.
        total: Общее число кампаний с учётом фильтра.
        limit: Запрошенный размер страницы.
        offset: Запрошенное смещение.
    """

    items: Sequence[Campaign]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class MessagePage:
    """Страница сообщений кампании.

    Attributes:
        items: Сообщения текущей страницы.
        total: Общее число сообщений с учётом фильтра.
        limit: Запрошенный размер страницы.
        offset: Запрошенное смещение.
    """

    items: Sequence[NotificationMessage]
    total: int
    limit: int
    offset: int


class CampaignService:
    """Создает и изменяет кампании до запуска и пишет аудит."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        """Сохранить фабрику единиц работы и часы."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def list_campaigns(
        self,
        *,
        status: CampaignStatus | None,
        limit: int,
        offset: int,
    ) -> CampaignPage:
        """Вернуть страницу кампаний.

        Raises:
            ValidationError: Размер страницы или смещение недопустимы.
        """
        validate_page(limit, offset)
        async with self._uow_factory() as uow:
            items = await uow.campaigns.list(status=status, limit=limit, offset=offset)
            total = await uow.campaigns.count(status=status)
        return CampaignPage(items=items, total=total, limit=limit, offset=offset)

    async def get_campaign(self, campaign_id: CampaignId) -> Campaign:
        """Вернуть кампанию по идентификатору.

        Raises:
            NotFoundError: Кампания не найдена.
        """
        async with self._uow_factory() as uow:
            campaign = await uow.campaigns.get(campaign_id)
        if campaign is None:
            raise NotFoundError(f"Кампания {campaign_id} не найдена")
        return campaign

    async def create_campaign(
        self,
        command: CreateCampaignCommand,
        context: RequestContext,
    ) -> Campaign:
        """Создать кампанию в статусе draft.

        Raises:
            ValidationError: Поля кампании недопустимы.
            ConflictError: Выбранная версия шаблона отсутствует или не активна.
        """
        now = self._clock.now()
        campaign = create_campaign(
            campaign_id=CampaignId(uuid4()),
            name=command.name,
            channel=command.channel,
            template_key=command.template_key,
            template_version=command.template_version,
            selection=command.selection,
            now=now,
        )
        async with self._uow_factory() as uow:
            await _require_active_template(
                uow,
                campaign.template_key,
                campaign.template_version,
            )
            await uow.campaigns.add(campaign)
            await uow.audit.add(
                _audit_event(
                    action=AuditAction.CAMPAIGN_CREATED,
                    campaign=campaign,
                    details={
                        "name": campaign.name,
                        "channel": campaign.channel,
                        "template_key": campaign.template_key,
                        "template_version": str(campaign.template_version),
                        "status": campaign.status.value,
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()
        return campaign

    async def update_campaign(
        self,
        campaign_id: CampaignId,
        command: UpdateCampaignCommand,
        context: RequestContext,
    ) -> Campaign:
        """Изменить кампанию в статусе draft.

        Raises:
            ValidationError: Поля кампании или пара шаблона недопустимы.
            NotFoundError: Кампания не найдена.
            InvalidStateError: Кампания уже не в статусе draft.
            ConflictError: Новая версия шаблона отсутствует или не активна.
        """
        if (
            command.name is None
            and command.template_key is None
            and command.template_version is None
            and command.selection is None
        ):
            raise ValidationError("Не передано ни одного поля для изменения")
        if (command.template_key is None) != (command.template_version is None):
            raise ValidationError("Ключ и версия шаблона должны передаваться вместе")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            campaign = await uow.campaigns.get(campaign_id)
            if campaign is None:
                raise NotFoundError(f"Кампания {campaign_id} не найдена")
            campaign.ensure_editable()
            template_key = campaign.template_key if command.template_key is None else command.template_key
            template_version = (
                campaign.template_version if command.template_version is None else command.template_version
            )
            selection = campaign.selection if command.selection is None else command.selection
            template_changed = (template_key, template_version) != (
                campaign.template_key,
                campaign.template_version,
            )
            changed = campaign.update_details(
                name=campaign.name if command.name is None else command.name,
                template_key=template_key,
                template_version=template_version,
                selection=selection,
                now=now,
            )
            if not changed:
                return campaign
            if template_changed:
                await _require_active_template(uow, template_key, template_version)
            await uow.campaigns.save(campaign)
            await uow.audit.add(
                _audit_event(
                    action=AuditAction.CAMPAIGN_UPDATED,
                    campaign=campaign,
                    details={
                        "name": campaign.name,
                        "template_key": campaign.template_key,
                        "template_version": str(campaign.template_version),
                        "changed": ",".join(changed),
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()
        return campaign

    async def schedule_campaign(
        self,
        campaign_id: CampaignId,
        schedule: ScheduleSpec,
        context: RequestContext,
    ) -> Campaign:
        """Поставить draft-кампанию в расписание и записать события.

        Raises:
            ValidationError: Правило запуска недопустимо.
            NotFoundError: Кампания не найдена.
            InvalidStateError: Кампания уже не в статусе draft.
        """
        now = self._clock.now()
        async with self._uow_factory() as uow:
            campaign = await uow.campaigns.get(campaign_id)
            if campaign is None:
                raise NotFoundError(f"Кампания {campaign_id} не найдена")
            campaign.schedule_for(schedule, now)
            scheduled = campaign.schedule
            if scheduled is None:
                raise ValidationError("Расписание кампании не сохранено")
            await uow.campaigns.save(campaign)
            await uow.events.add_scheduled(
                CampaignScheduled(
                    campaign_id=campaign.id,
                    schedule=scheduled,
                    occurred_at=now,
                ),
                _correlation_id(context),
                context.trace_id,
            )
            await uow.audit.add(
                _audit_event(
                    action=AuditAction.CAMPAIGN_SCHEDULED,
                    campaign=campaign,
                    details={
                        "name": campaign.name,
                        "template_key": campaign.template_key,
                        "template_version": str(campaign.template_version),
                        **_schedule_details(scheduled),
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()
        return campaign

    async def cancel_campaign(
        self,
        campaign_id: CampaignId,
        context: RequestContext,
    ) -> Campaign:
        """Отменить запланированную или выполняющуюся кампанию.

        Raises:
            NotFoundError: Кампания не найдена.
            InvalidStateError: Кампания в статусе draft или уже завершена.
        """
        now = self._clock.now()
        async with self._uow_factory() as uow:
            campaign = await uow.campaigns.get(campaign_id)
            if campaign is None:
                raise NotFoundError(f"Кампания {campaign_id} не найдена")
            was_running = campaign.cancel(now)
            await uow.campaigns.save(campaign)
            cancelled_messages = 0
            if was_running:
                cancelled_messages = await uow.messages.cancel_pending(campaign.id)
            else:
                await uow.events.add_cancelled(
                    CampaignCancelled(campaign_id=campaign.id, occurred_at=now),
                    _correlation_id(context),
                    context.trace_id,
                )
            await uow.audit.add(
                _audit_event(
                    action=AuditAction.CAMPAIGN_CANCELLED,
                    campaign=campaign,
                    details={
                        "name": campaign.name,
                        "template_key": campaign.template_key,
                        "template_version": str(campaign.template_version),
                        "status": campaign.status.value,
                        "cancelled_messages": str(cancelled_messages),
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()
        return campaign

    async def start_campaign(
        self,
        campaign_id: CampaignId,
        context: RequestContext,
    ) -> Campaign:
        """Запустить draft-кампанию и поставить campaign.start в outbox.

        Raises:
            NotFoundError: Кампания не найдена.
            InvalidStateError: Кампания уже не в статусе draft.
        """
        now = self._clock.now()
        async with self._uow_factory() as uow:
            campaign = await uow.campaigns.get(campaign_id)
            if campaign is None:
                raise NotFoundError(f"Кампания {campaign_id} не найдена")
            if campaign.status is not CampaignStatus.DRAFT:
                raise InvalidStateError(f"Кампания в статусе {campaign.status.value} не может быть запущена")
            campaign.mark_running(now)
            await uow.campaigns.save(campaign)
            await uow.events.add_start(
                CampaignStart(
                    campaign_id=campaign.id,
                    scheduled_for=now,
                    occurred_at=now,
                ),
                _correlation_id(context),
                context.trace_id,
            )
            await uow.audit.add(
                _audit_event(
                    action=AuditAction.CAMPAIGN_STARTED,
                    campaign=campaign,
                    details={
                        "name": campaign.name,
                        "template_key": campaign.template_key,
                        "template_version": str(campaign.template_version),
                        "status": campaign.status.value,
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()
        return campaign

    async def list_messages(
        self,
        campaign_id: CampaignId,
        *,
        status: MessageStatus | None,
        limit: int,
        offset: int,
    ) -> MessagePage:
        """Вернуть страницу сообщений кампании.

        Raises:
            ValidationError: Недопустимые параметры страницы.
            NotFoundError: Кампания не найдена.
        """
        validate_page(limit, offset)
        async with self._uow_factory() as uow:
            campaign = await uow.campaigns.get(campaign_id)
            if campaign is None:
                raise NotFoundError(f"Кампания {campaign_id} не найдена")
            items = await uow.messages.list_by_campaign(
                campaign_id,
                status=status,
                limit=limit,
                offset=offset,
            )
            total = await uow.messages.count_by_campaign(campaign_id, status=status)
        return MessagePage(items=items, total=total, limit=limit, offset=offset)

    async def get_message(
        self,
        campaign_id: CampaignId,
        message_id: MessageId,
    ) -> NotificationMessage:
        """Вернуть сообщение кампании.

        Raises:
            NotFoundError: Кампания или сообщение не найдены.
        """
        async with self._uow_factory() as uow:
            campaign = await uow.campaigns.get(campaign_id)
            if campaign is None:
                raise NotFoundError(f"Кампания {campaign_id} не найдена")
            message = await uow.messages.get(message_id)
        if message is None or message.campaign_id != campaign_id:
            raise NotFoundError(f"Сообщение {message_id} не найдено в кампании")
        return message


async def _require_active_template(
    uow: UnitOfWork,
    key: TemplateKey,
    version: int,
) -> NotificationTemplate:
    """Проверить, что выбранная версия шаблона активна.

    Raises:
        ConflictError: Версия отсутствует или не активна.
    """
    template = await uow.templates.get(key, version)
    if template is None:
        raise ConflictError(f"Версия {version} шаблона {key} не найдена")
    if template.status is not TemplateStatus.ACTIVE:
        raise ConflictError(f"Версия {version} шаблона {key} не активна и не может быть выбрана")
    return template


def _correlation_id(context: RequestContext) -> str:
    """Вернуть идентификатор корреляции или создать новый."""
    return context.correlation_id or uuid4().hex


def _schedule_details(schedule: ScheduleSpec) -> dict[str, str]:
    """Собрать поля расписания для audit-события."""
    details = {
        "schedule_kind": schedule.kind.value,
        "timezone": schedule.timezone,
    }
    if schedule.run_at is not None:
        details["run_at"] = schedule.run_at.astimezone(UTC).isoformat()
    if schedule.cron is not None:
        details["cron"] = schedule.cron
    return details


def _audit_event(
    *,
    action: AuditAction,
    campaign: Campaign,
    details: dict[str, str],
    now: datetime,
    context: RequestContext,
) -> AuditEvent:
    """Собрать audit-событие кампании."""
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=now,
        service=NOTIFICATIONS_SERVICE,
        actor=AuditActor(type=AuditActorType.OPERATOR, identifier=None),
        action=action,
        entity_type=CAMPAIGN_ENTITY_TYPE,
        entity_id=str(campaign.id),
        campaign_id=campaign.id,
        message_id=None,
        channel=campaign.channel,
        outcome=AuditOutcome.SUCCESS,
        details=details,
        correlation_id=context.correlation_id or uuid4().hex,
        trace_id=context.trace_id,
    )
