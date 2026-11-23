"""Обработка результатов отправки сообщений и повторов."""

import logging
from datetime import datetime, timedelta
from typing import Final
from uuid import uuid4

from notifications.application.common import RequestContext
from notifications.application.composition import build_command
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
    DeliveryOutcome,
    MessageAttempt,
    MessageFailed,
    MessageSent,
    MessageStatus,
    NotificationMessage,
)
from notifications.ports.clock import Clock
from notifications.ports.uow import UnitOfWorkFactory

logger = logging.getLogger(__name__)

NOTIFICATIONS_SERVICE: Final = "notifications"
MESSAGE_ENTITY_TYPE: Final = "message"
CAMPAIGN_ENTITY_TYPE: Final = "campaign"


class MessageResultService:
    """Применяет message.sent и message.failed и планирует повторы."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        settings: Settings,
    ) -> None:
        """Сохранить зависимости сценария результатов."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._settings = settings

    async def handle_sent(
        self,
        event: MessageSent,
        context: RequestContext,
    ) -> None:
        """Зафиксировать успешную отправку сообщения."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            message = await uow.messages.get(event.message_id)
            if message is None:
                logger.warning("Сообщение %s из message.sent не найдено", event.message_id)
                return
            if message.campaign_id != event.campaign_id:
                logger.warning(
                    "message.sent ссылается на чужую кампанию: %s и %s",
                    event.campaign_id,
                    message.campaign_id,
                )
                return
            if message.status in (
                MessageStatus.SENT,
                MessageStatus.FAILED,
                MessageStatus.CANCELLED,
            ):
                return
            if event.attempt_number <= message.attempt_count:
                return
            message.mark_sent(
                attempt_number=event.attempt_number,
                occurred_at=now,
            )
            await uow.messages.save(message)
            await uow.attempts.add(
                MessageAttempt(
                    message_id=message.id,
                    attempt_number=event.attempt_number,
                    outcome=DeliveryOutcome.SENT,
                    occurred_at=now,
                    provider_message_id=event.provider_message_id,
                    provider_error_code=None,
                )
            )
            await uow.audit.add(
                _message_audit_event(
                    action=AuditAction.MESSAGE_SENT,
                    message=message,
                    outcome=AuditOutcome.SUCCESS,
                    details={
                        "attempt_number": str(event.attempt_number),
                        "channel": message.channel,
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()
        await self._complete_campaign_if_ready(message.campaign_id, now, context)

    async def handle_failed(
        self,
        event: MessageFailed,
        context: RequestContext,
    ) -> None:
        """Зафиксировать ошибку и запланировать повтор через outbox."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            message = await uow.messages.get(event.message_id)
            if message is None:
                logger.warning("Сообщение %s из message.failed не найдено", event.message_id)
                return
            if message.campaign_id != event.campaign_id:
                logger.warning(
                    "message.failed ссылается на чужую кампанию: %s и %s",
                    event.campaign_id,
                    message.campaign_id,
                )
                return
            if message.status in (
                MessageStatus.SENT,
                MessageStatus.FAILED,
                MessageStatus.CANCELLED,
            ):
                return
            if event.attempt_number <= message.attempt_count:
                return
            retry_at = self._retry_at(event, now)
            message.mark_failed(
                attempt_number=event.attempt_number,
                occurred_at=now,
                error_code=event.error_code,
                error_message=event.error_message,
                retry_at=retry_at,
            )
            await uow.messages.save(message)
            await uow.attempts.add(
                MessageAttempt(
                    message_id=message.id,
                    attempt_number=event.attempt_number,
                    outcome=event.outcome,
                    occurred_at=now,
                    provider_message_id=None,
                    provider_error_code=event.error_code,
                )
            )
            if retry_at is not None:
                await uow.message_commands.add(
                    build_command(message),
                    _correlation_id(context),
                    context.trace_id,
                    occurred_at=now,
                    available_at=retry_at,
                )
            await uow.audit.add(
                _message_audit_event(
                    action=AuditAction.MESSAGE_FAILED,
                    message=message,
                    outcome=AuditOutcome.FAILURE,
                    details={
                        "attempt_number": str(event.attempt_number),
                        "channel": message.channel,
                        "outcome": event.outcome.value,
                        "retryable": str(event.retryable).lower(),
                        "retry_at": retry_at.isoformat() if retry_at is not None else "",
                        "error_code": event.error_code or "",
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()
        await self._complete_campaign_if_ready(message.campaign_id, now, context)

    def _retry_at(self, event: MessageFailed, now: datetime) -> datetime | None:
        """Рассчитать время повтора для временной ошибки."""
        if not event.retryable or event.attempt_number >= self._settings.message_max_attempts:
            return None
        delay = self._settings.message_retry_base_seconds * (2 ** (event.attempt_number - 1))
        delay = min(delay, self._settings.message_retry_max_seconds)
        return now + timedelta(seconds=delay)

    async def _complete_campaign_if_ready(
        self,
        campaign_id: CampaignId,
        now: datetime,
        context: RequestContext,
    ) -> None:
        """Завершить кампанию после коммита результата сообщения."""
        async with self._uow_factory() as uow:
            pending = await uow.messages.count_not_terminal(campaign_id)
            if pending:
                return
            if not await uow.campaigns.complete_if_running(campaign_id, now):
                return
            campaign = await uow.campaigns.get(campaign_id)
            if campaign is None:
                return
            await uow.audit.add(
                _campaign_audit_event(
                    action=AuditAction.CAMPAIGN_COMPLETED,
                    campaign=campaign,
                    details={
                        "name": campaign.name,
                        "selected_debtors": str(campaign.selected_debtors),
                        "sent": str(
                            await uow.messages.count_by_campaign(
                                campaign_id,
                                MessageStatus.SENT,
                            )
                        ),
                        "failed": str(
                            await uow.messages.count_by_campaign(
                                campaign_id,
                                MessageStatus.FAILED,
                            )
                        ),
                        "cancelled": str(
                            await uow.messages.count_by_campaign(
                                campaign_id,
                                MessageStatus.CANCELLED,
                            )
                        ),
                    },
                    now=now,
                    context=context,
                )
            )
            await uow.commit()


def _correlation_id(context: RequestContext) -> str:
    """Вернуть идентификатор корреляции или создать новый."""
    return context.correlation_id or uuid4().hex


def _message_audit_event(
    *,
    action: AuditAction,
    message: NotificationMessage,
    outcome: AuditOutcome,
    details: dict[str, str],
    now: datetime,
    context: RequestContext,
) -> AuditEvent:
    """Собрать audit-событие сообщения."""
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=now,
        service=NOTIFICATIONS_SERVICE,
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier=None),
        action=action,
        entity_type=MESSAGE_ENTITY_TYPE,
        entity_id=str(message.id),
        campaign_id=message.campaign_id,
        message_id=message.id,
        channel=message.channel,
        outcome=outcome,
        details=details,
        correlation_id=_correlation_id(context),
        trace_id=context.trace_id,
    )


def _campaign_audit_event(
    *,
    action: AuditAction,
    campaign: Campaign,
    details: dict[str, str],
    now: datetime,
    context: RequestContext,
) -> AuditEvent:
    """Собрать audit-событие кампании из результата отправки."""
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=now,
        service=NOTIFICATIONS_SERVICE,
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier=None),
        action=action,
        entity_type=CAMPAIGN_ENTITY_TYPE,
        entity_id=str(campaign.id),
        campaign_id=campaign.id,
        message_id=None,
        channel=campaign.channel,
        outcome=AuditOutcome.SUCCESS,
        details=details,
        correlation_id=_correlation_id(context),
        trace_id=context.trace_id,
    )
