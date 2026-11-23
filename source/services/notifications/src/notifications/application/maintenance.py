"""Фоновое обслуживание: retention и восстановление зависших состояний."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import uuid4

from notifications.application.composition import build_command
from notifications.domain import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditOutcome,
    Campaign,
    CampaignStart,
    MessageId,
    MessageStatus,
    NotificationMessage,
)
from notifications.infrastructure.metrics import (
    MAINTENANCE_TABLE_ATTRIBUTE,
    Metrics,
)
from notifications.ports.clock import Clock
from notifications.ports.uow import UnitOfWork, UnitOfWorkFactory

logger = logging.getLogger(__name__)

NOTIFICATIONS_SERVICE: Final = "notifications"
MAINTENANCE_CORRELATION_ID: Final = "maintenance"
WORKER_TASK_NAME: Final = "notifications-maintenance"
STOP_TIMEOUT_SECONDS: float = 10.0
OUTBOX_EXHAUSTED_ERROR_CODE: Final = "outbox_publish_exhausted"
OUTBOX_EXHAUSTED_ERROR_MESSAGE: Final = "Публикация message.send исчерпала попытки outbox"


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    """Итог одной итерации обслуживания.

    Attributes:
        requeued_messages: Сколько сообщений повторно поставлено в очередь.
        requeued_campaigns: Сколько кампаний повторно запущено.
        completed_campaigns: Сколько кампаний завершено.
        exhausted_messages: Сколько сообщений закрыто из-за отказа outbox.
        deleted_outbox: Сколько записей outbox удалено.
        deleted_attempts: Сколько попыток удалено.
    """

    requeued_messages: int
    requeued_campaigns: int
    completed_campaigns: int
    exhausted_messages: int
    deleted_outbox: int
    deleted_attempts: int


class MaintenanceService:
    """Выполняет retention и восстановление после сбоев."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        retention_days: int,
        recovery_grace_seconds: float,
        batch_size: int,
        outbox_max_attempts: int,
        metrics: Metrics | None = None,
    ) -> None:
        """Сохранить параметры обслуживания."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._retention_days = retention_days
        self._recovery_grace = timedelta(seconds=recovery_grace_seconds)
        self._batch_size = batch_size
        self._outbox_max_attempts = outbox_max_attempts
        self._metrics = metrics

    async def run_once(self) -> MaintenanceResult:
        """Выполнить одну итерацию retention и восстановления."""
        now = self._clock.now()
        cutoff = now - timedelta(days=self._retention_days)
        requeued_messages = 0
        requeued_campaigns = 0
        completed_campaigns = 0
        exhausted_messages = 0
        async with self._uow_factory() as uow:
            deleted_outbox = await uow.maintenance.delete_published_outbox_before(cutoff)
            deleted_attempts = await uow.maintenance.delete_attempts_before(cutoff)

            due_messages = await uow.maintenance.list_retry_due(now, self._batch_size)
            for message in due_messages:
                await uow.message_commands.add(
                    build_command(message),
                    MAINTENANCE_CORRELATION_ID,
                    None,
                    occurred_at=now,
                    available_at=now,
                )
                message.mark_requeued()
                await uow.messages.save(message)
                requeued_messages += 1

            stuck_campaigns = await uow.maintenance.list_stuck_campaigns(
                now - self._recovery_grace,
                self._batch_size,
            )
            for campaign in stuck_campaigns:
                await uow.events.add_start(
                    CampaignStart(
                        campaign_id=campaign.id,
                        scheduled_for=now,
                        occurred_at=now,
                    ),
                    MAINTENANCE_CORRELATION_ID,
                    None,
                )
                requeued_campaigns += 1

            exhausted = await uow.maintenance.list_exhausted_message_send(
                self._outbox_max_attempts,
                self._batch_size,
            )
            for command in exhausted:
                exhausted_message = await uow.messages.get(MessageId(command.message_id))
                if exhausted_message is not None and exhausted_message.status not in (
                    MessageStatus.SENT,
                    MessageStatus.FAILED,
                    MessageStatus.CANCELLED,
                ):
                    exhausted_message.mark_failed(
                        attempt_number=max(1, exhausted_message.attempt_count),
                        occurred_at=now,
                        error_code=OUTBOX_EXHAUSTED_ERROR_CODE,
                        error_message=OUTBOX_EXHAUSTED_ERROR_MESSAGE,
                        retry_at=None,
                    )
                    await uow.messages.save(exhausted_message)
                    await uow.audit.add(
                        _message_failed_event(
                            message=exhausted_message,
                            now=now,
                            reason=OUTBOX_EXHAUSTED_ERROR_MESSAGE,
                        )
                    )
                    exhausted_messages += 1
                await uow.maintenance.mark_outbox_failed(command.outbox_id, now)

            ready_campaigns = await uow.maintenance.list_completable_campaigns(self._batch_size)
            for campaign in ready_campaigns:
                campaign.complete(now)
                await uow.campaigns.save(campaign)
                await uow.audit.add(_completed_event(campaign, now, await self._counts(uow, campaign)))
                completed_campaigns += 1

            await uow.commit()

        result = MaintenanceResult(
            requeued_messages=requeued_messages,
            requeued_campaigns=requeued_campaigns,
            completed_campaigns=completed_campaigns,
            exhausted_messages=exhausted_messages,
            deleted_outbox=deleted_outbox,
            deleted_attempts=deleted_attempts,
        )
        self._record_metrics(result)
        if any(
            (
                result.requeued_messages,
                result.requeued_campaigns,
                result.completed_campaigns,
                result.exhausted_messages,
                result.deleted_outbox,
                result.deleted_attempts,
            )
        ):
            logger.info(
                "Обслуживание: сообщений %s, кампаний %s, завершено %s, "
                "исчерпано outbox %s, удалено outbox %s, попыток %s",
                result.requeued_messages,
                result.requeued_campaigns,
                result.completed_campaigns,
                result.exhausted_messages,
                result.deleted_outbox,
                result.deleted_attempts,
            )
        return result

    async def _counts(self, uow: UnitOfWork, campaign: Campaign) -> dict[str, str]:
        """Собрать счетчики сообщений кампании."""
        return {
            "sent": str(await uow.messages.count_by_campaign(campaign.id, MessageStatus.SENT)),
            "failed": str(await uow.messages.count_by_campaign(campaign.id, MessageStatus.FAILED)),
            "cancelled": str(
                await uow.messages.count_by_campaign(
                    campaign.id,
                    MessageStatus.CANCELLED,
                )
            ),
        }

    def _record_metrics(self, result: MaintenanceResult) -> None:
        """Записать метрики обслуживания."""
        metrics = self._metrics
        if metrics is None:
            return
        metrics.maintenance_requeued.add(
            result.requeued_messages,
            {MAINTENANCE_TABLE_ATTRIBUTE: "messages"},
        )
        metrics.maintenance_requeued.add(
            result.requeued_campaigns,
            {MAINTENANCE_TABLE_ATTRIBUTE: "campaigns"},
        )
        metrics.maintenance_completed.add(result.completed_campaigns)
        metrics.maintenance_exhausted.add(result.exhausted_messages)
        metrics.maintenance_deleted.add(
            result.deleted_outbox,
            {MAINTENANCE_TABLE_ATTRIBUTE: "outbox"},
        )
        metrics.maintenance_deleted.add(
            result.deleted_attempts,
            {MAINTENANCE_TABLE_ATTRIBUTE: "message_attempts"},
        )


class MaintenanceWorker:
    """Периодически запускает обслуживание."""

    def __init__(
        self,
        service: MaintenanceService,
        interval_seconds: float,
        clock: Clock,
    ) -> None:
        """Сохранить сервис, интервал и часы."""
        self._service = service
        self._interval_seconds = interval_seconds
        self._clock = clock
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_error: str | None = None
        self._last_success_at: datetime | None = None

    @property
    def last_error(self) -> str | None:
        """Вернуть последнюю ошибку обслуживания."""
        return self._last_error

    @property
    def last_success_at(self) -> datetime | None:
        """Вернуть время последней успешной итерации."""
        return self._last_success_at

    @property
    def is_running(self) -> bool:
        """Вернуть признак активной фоновой задачи."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Запустить фоновую задачу."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=WORKER_TASK_NAME)

    async def stop(self) -> None:
        """Остановить фоновую задачу."""
        self._stop.set()
        task, self._task = self._task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=STOP_TIMEOUT_SECONDS)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        """Выполнять обслуживание до остановки."""
        while not self._stop.is_set():
            try:
                await self._service.run_once()
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Итерация обслуживания завершилась ошибкой")
            else:
                self._last_error = None
                self._last_success_at = self._clock.now()
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._interval_seconds,
                )
            except TimeoutError:
                continue


def _message_failed_event(
    *,
    message: NotificationMessage,
    now: datetime,
    reason: str,
) -> AuditEvent:
    """Создать audit-событие окончательного отказа сообщения."""
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=now,
        service=NOTIFICATIONS_SERVICE,
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier=None),
        action=AuditAction.MESSAGE_FAILED,
        entity_type="message",
        entity_id=str(message.id),
        campaign_id=message.campaign_id,
        message_id=message.id,
        channel=message.channel,
        outcome=AuditOutcome.FAILURE,
        details={
            "attempt_number": str(message.attempt_count),
            "channel": message.channel,
            "outcome": "permanent_failure",
            "retryable": "false",
            "error_code": OUTBOX_EXHAUSTED_ERROR_CODE,
            "reason": reason,
        },
        correlation_id=MAINTENANCE_CORRELATION_ID,
        trace_id=None,
    )


def _completed_event(
    campaign: Campaign,
    now: datetime,
    counts: dict[str, str],
) -> AuditEvent:
    """Создать audit-событие завершения кампании обслуживанием."""
    details = {
        "name": campaign.name,
        "selected_debtors": str(campaign.selected_debtors),
        "reason": "recovery",
        **counts,
    }
    return AuditEvent(
        event_id=AuditEventId(uuid4()),
        occurred_at=now,
        service=NOTIFICATIONS_SERVICE,
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier=None),
        action=AuditAction.CAMPAIGN_COMPLETED,
        entity_type="campaign",
        entity_id=str(campaign.id),
        campaign_id=campaign.id,
        message_id=None,
        channel=campaign.channel,
        outcome=AuditOutcome.SUCCESS,
        details=details,
        correlation_id=MAINTENANCE_CORRELATION_ID,
        trace_id=None,
    )
