"""Запуск кампании: полная выборка АБС и создание сообщений."""

import logging
from datetime import datetime
from typing import Final
from uuid import uuid4

from notifications.application.common import RequestContext
from notifications.application.composition import (
    build_command,
    build_messages,
    build_snapshots,
)
from notifications.application.debtor_selection import (
    SelectionError,
    build_debtor_filter,
    fetch_full_selection,
)
from notifications.config import Settings
from notifications.domain import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditOutcome,
    Campaign,
    CampaignId,
    CampaignStart,
    CampaignStatus,
    InvalidStateError,
    NotificationMessage,
    ValidationError,
)
from notifications.infrastructure.metrics import Metrics
from notifications.ports.abs import AbsDebtorSource, AbsPermanentError
from notifications.ports.clock import Clock
from notifications.ports.uow import UnitOfWorkFactory

logger = logging.getLogger(__name__)

NOTIFICATIONS_SERVICE: Final = "notifications"
CAMPAIGN_ENTITY_TYPE: Final = "campaign"
TERMINAL_STATUSES: Final = frozenset(
    {CampaignStatus.COMPLETED, CampaignStatus.CANCELLED, CampaignStatus.FAILED}
)


class CampaignStartTransientError(Exception):
    """Кампания уже обрабатывается другим потребителем."""


class CampaignStartService:
    """Выполняет выборку и создает сообщения по событию campaign.start."""

    def __init__(
        self,
        source: AbsDebtorSource,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        settings: Settings,
        metrics: Metrics | None = None,
    ) -> None:
        """Сохранить зависимости сценария запуска."""
        self._source = source
        self._uow_factory = uow_factory
        self._clock = clock
        self._settings = settings
        self._metrics = metrics

    async def handle(
        self,
        event: CampaignStart,
        context: RequestContext,
    ) -> None:
        """Обработать событие запуска кампании.

        Raises:
            CampaignStartTransientError: Кампанию уже обрабатывает другой потребитель.
            AbsTransientError: АБС временно недоступна, нужен повтор.
        """
        campaign = await self._load(event.campaign_id)
        if campaign is None:
            logger.warning("Кампания %s из campaign.start не найдена", event.campaign_id)
            return
        if campaign.status in TERMINAL_STATUSES or campaign.messages_created_at is not None:
            logger.info("Кампания %s уже обработана", campaign.id)
            return
        try:
            debtor_filter = build_debtor_filter(campaign.selection.criteria)
            selection = await fetch_full_selection(
                self._source,
                debtor_filter,
                self._settings.debtor_page_size,
                self._settings.debtor_selection_max_total,
                self._clock,
            )
        except (ValidationError, SelectionError, AbsPermanentError) as exc:
            await self._fail(campaign.id, str(exc), context)
            return

        now = self._clock.now()
        snapshots = build_snapshots(campaign.id, selection.debtors, selection.fetched_at)
        messages = build_messages(
            campaign,
            selection.debtors,
            now,
            self._settings.message_max_attempts,
        )
        correlation_id = context.correlation_id or uuid4().hex
        async with self._uow_factory() as uow:
            if not await uow.campaigns.try_advisory_lock(campaign.id):
                raise CampaignStartTransientError(f"Кампания {campaign.id} уже обрабатывается")
            current = await uow.campaigns.get(campaign.id)
            if current is None:
                return
            if current.status in TERMINAL_STATUSES or current.messages_created_at is not None:
                return
            transitioned = current.mark_running(now)
            await uow.snapshots.replace_for_campaign(current.id, snapshots)
            if messages:
                await uow.messages.add_many(messages)
            for message in messages:
                await uow.message_commands.add(
                    build_command(message),
                    correlation_id,
                    context.trace_id,
                )
                await uow.audit.add(_message_queued_event(message, now, context))
            current.selected_debtors = len(selection.debtors)
            current.selection_expected = selection.expected_total
            current.selection_completed_at = selection.fetched_at
            current.mark_messages_created(now)
            if not messages:
                current.complete(now)
            await uow.campaigns.save(current)
            if transitioned:
                await uow.audit.add(
                    _audit_event(
                        action=AuditAction.CAMPAIGN_STARTED,
                        campaign=current,
                        details={
                            "name": current.name,
                            "template_key": current.template_key,
                            "template_version": str(current.template_version),
                            "selected_debtors": str(current.selected_debtors),
                            "messages_created": str(len(messages)),
                            "expected_total": str(selection.expected_total),
                        },
                        now=now,
                        context=context,
                    )
                )
            if not messages:
                await uow.audit.add(
                    _audit_event(
                        action=AuditAction.CAMPAIGN_COMPLETED,
                        campaign=current,
                        details={
                            "name": current.name,
                            "selected_debtors": str(current.selected_debtors),
                            "reason": "no_recipients",
                        },
                        now=now,
                        context=context,
                    )
                )
            await uow.commit()
        if self._metrics is not None:
            self._metrics.campaign_debtors.record(len(selection.debtors))
            self._metrics.campaign_messages.record(len(messages))
        logger.info(
            "Кампания %s выгрузила %s должников и создала %s сообщений",
            campaign.id,
            len(selection.debtors),
            len(messages),
        )

    async def _load(self, campaign_id: CampaignId) -> Campaign | None:
        """Прочитать кампанию без транзакционных изменений."""
        async with self._uow_factory() as uow:
            return await uow.campaigns.get(campaign_id)

    async def _fail(
        self,
        campaign_id: CampaignId,
        reason: str,
        context: RequestContext,
    ) -> None:
        """Перевести кампанию в failed и записать аудит."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            campaign = await uow.campaigns.get(campaign_id)
            if campaign is None or campaign.status in TERMINAL_STATUSES:
                return
            try:
                campaign.fail(reason, now)
            except InvalidStateError:
                return
            await uow.campaigns.save(campaign)
            await uow.audit.add(
                _audit_event(
                    action=AuditAction.CAMPAIGN_FAILED,
                    campaign=campaign,
                    details={
                        "name": campaign.name,
                        "template_key": campaign.template_key,
                        "template_version": str(campaign.template_version),
                        "reason": reason,
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()
        logger.error("Кампания %s завершилась ошибкой: %s", campaign_id, reason)


def _message_queued_event(
    message: NotificationMessage,
    now: datetime,
    context: RequestContext,
) -> AuditEvent:
    """Собрать audit-событие постановки сообщения в очередь."""
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=now,
        service=NOTIFICATIONS_SERVICE,
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier=None),
        action=AuditAction.MESSAGE_QUEUED,
        entity_type="message",
        entity_id=str(message.id),
        campaign_id=message.campaign_id,
        message_id=message.id,
        channel=message.channel,
        outcome=AuditOutcome.SUCCESS,
        details={
            "channel": message.channel,
            "template_key": message.template_key,
            "template_version": str(message.template_version),
        },
        correlation_id=context.correlation_id or uuid4().hex,
        trace_id=context.trace_id,
    )


def _audit_event(
    *,
    action: AuditAction,
    campaign: Campaign,
    details: dict[str, str],
    now: datetime,
    context: RequestContext,
) -> AuditEvent:
    """Собрать audit-событие запуска кампании."""
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
