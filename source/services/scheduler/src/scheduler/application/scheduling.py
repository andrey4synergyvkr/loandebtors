"""Сценарии планирования, срабатывания и восстановления расписаний."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid5

from opentelemetry import trace

from scheduler.application.common import MessageContext
from scheduler.domain import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditOutcome,
    CampaignCancelled,
    CampaignId,
    CampaignSchedule,
    CampaignScheduled,
    CampaignStart,
    ScheduleKind,
    ScheduleSpec,
    ScheduleStatus,
    ValidationError,
)
from scheduler.infrastructure.correlation import new_correlation_id
from scheduler.infrastructure.metrics import Metrics
from scheduler.ports.clock import Clock
from scheduler.ports.jobs import JobRegistrar
from scheduler.ports.uow import UnitOfWorkFactory

logger = logging.getLogger(__name__)

SCHEDULER_SERVICE: Final = "scheduler"
CAMPAIGN_ENTITY_TYPE: Final = "campaign"
AUDIT_NAMESPACE: Final = UUID("9e1b3d7c-5f2a-4c8e-9a1b-7d3c5e9f2a4b")
TRIGGER_MAX_ATTEMPTS: Final = 3
TRIGGER_RETRY_BASE_SECONDS: Final = 0.2


class CampaignTrigger:
    """Срабатывание задания: публикует campaign.start и пишет аудит."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registrar: JobRegistrar,
        clock: Clock,
        metrics: Metrics,
        max_attempts: int = TRIGGER_MAX_ATTEMPTS,
    ) -> None:
        """Сохранить зависимости сценария срабатывания."""
        self._uow_factory = uow_factory
        self._registrar = registrar
        self._clock = clock
        self._metrics = metrics
        self._max_attempts = max_attempts

    async def execute(self, campaign_id: CampaignId) -> None:
        """Обработать срабатывание задания с ограниченным повтором."""
        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._execute_once(campaign_id)
                return
            except Exception:
                if attempt >= self._max_attempts:
                    logger.exception(
                        "Срабатывание задания кампании %s завершилось ошибкой",
                        campaign_id,
                    )
                    raise
                logger.warning(
                    "Повтор срабатывания задания кампании %s, попытка %s",
                    campaign_id,
                    attempt,
                    exc_info=True,
                )
                await asyncio.sleep(TRIGGER_RETRY_BASE_SECONDS * attempt)

    async def _execute_once(self, campaign_id: CampaignId) -> None:
        """Выполнить одну попытку срабатывания задания."""
        now = self._clock.now()
        remove_job = False
        async with self._uow_factory() as uow:
            schedule = await uow.schedules.get(campaign_id)
            cancelled_at = await uow.cancellations.get_occurred_at(campaign_id)
            if cancelled_at is not None:
                if schedule is not None and schedule.cancel(now):
                    await uow.schedules.save(schedule)
                    await uow.outbox.add_audit(
                        _audit_event(
                            action=AuditAction.CAMPAIGN_CANCELLED,
                            campaign_id=campaign_id,
                            occurred_at=cancelled_at,
                            details={"status": schedule.status.value},
                            context=MessageContext(
                                correlation_id=schedule.correlation_id or new_correlation_id(),
                                trace_id=_current_trace_id(),
                            ),
                        )
                    )
                await uow.commit()
                remove_job = True
            elif schedule is None or schedule.status is not ScheduleStatus.ACTIVE:
                remove_job = True
            else:
                scheduled_for = schedule.next_run_at or now
                next_run_at = await self._registrar.next_run_at(campaign_id)
                schedule.mark_triggered(triggered_at=now, next_run_at=next_run_at, now=now)
                correlation_id = schedule.correlation_id or new_correlation_id()
                context = MessageContext(correlation_id=correlation_id, trace_id=_current_trace_id())
                await uow.schedules.save(schedule)
                await uow.outbox.add_campaign_start(
                    CampaignStart(
                        campaign_id=campaign_id,
                        scheduled_for=scheduled_for,
                        occurred_at=now,
                    ),
                    correlation_id=correlation_id,
                    trace_id=context.trace_id,
                )
                await uow.outbox.add_audit(
                    _audit_event(
                        action=AuditAction.CAMPAIGN_STARTED,
                        campaign_id=campaign_id,
                        occurred_at=now,
                        details={
                            "scheduled_for": scheduled_for.isoformat(),
                            "status": schedule.status.value,
                        },
                        context=context,
                    )
                )
                await uow.commit()
        if remove_job:
            await self._registrar.remove(campaign_id)
            logger.info("Задание кампании %s снято: активное расписание отсутствует", campaign_id)
            return
        self._metrics.jobs_triggered.add(1)


class ScheduleService:
    """Принимает команды расписания и управляет заданиями планировщика."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registrar: JobRegistrar,
        clock: Clock,
        metrics: Metrics,
        trigger: CampaignTrigger,
        misfire_grace_seconds: int,
    ) -> None:
        """Сохранить зависимости сценариев расписания."""
        self._uow_factory = uow_factory
        self._registrar = registrar
        self._clock = clock
        self._metrics = metrics
        self._trigger = trigger
        self._misfire_grace_seconds = misfire_grace_seconds

    async def schedule(self, event: CampaignScheduled, context: MessageContext) -> None:
        """Поставить кампанию в расписание или обновить существующее задание.

        Raises:
            ValidationError: Расписание невозможно зарегистрировать.
        """
        await self._registrar.validate(event.schedule)
        now = self._clock.now()
        self._ensure_run_at_not_missed(event.schedule, now)
        async with self._uow_factory() as uow:
            cancelled_at = await uow.cancellations.get_occurred_at(event.campaign_id)
            if cancelled_at is not None:
                logger.info(
                    "Кампания %s отменена, расписание не создается",
                    event.campaign_id,
                )
                return
            existing = await uow.schedules.get(event.campaign_id)
            if existing is None:
                schedule = CampaignSchedule.create(
                    campaign_id=event.campaign_id,
                    schedule=event.schedule,
                    now=now,
                    correlation_id=context.correlation_id,
                )
            else:
                schedule = existing
                schedule.reschedule(event.schedule, now=now, correlation_id=context.correlation_id)
            await uow.schedules.save(schedule)
            await uow.outbox.add_audit(
                _audit_event(
                    action=AuditAction.CAMPAIGN_SCHEDULED,
                    campaign_id=event.campaign_id,
                    occurred_at=event.occurred_at,
                    details=_schedule_details(event.schedule),
                    context=context,
                )
            )
            await uow.commit()

        next_run_at = await self._registrar.register(schedule, self._trigger.execute)

        cancelled_at = None
        async with self._uow_factory() as uow:
            cancelled_at = await uow.cancellations.get_occurred_at(event.campaign_id)
            current = await uow.schedules.get(event.campaign_id)
            if cancelled_at is not None:
                if current is not None and current.cancel(self._clock.now()):
                    await uow.schedules.save(current)
                    await uow.outbox.add_audit(
                        _audit_event(
                            action=AuditAction.CAMPAIGN_CANCELLED,
                            campaign_id=event.campaign_id,
                            occurred_at=cancelled_at,
                            details={"status": ScheduleStatus.CANCELLED.value},
                            context=context,
                        )
                    )
                await uow.commit()
            else:
                if current is not None:
                    current.set_next_run(next_run_at, now=self._clock.now())
                    await uow.schedules.save(current)
                await uow.commit()

        if cancelled_at is not None:
            await self._registrar.remove(event.campaign_id)
            logger.info(
                "Задание кампании %s снято: кампания отменена",
                event.campaign_id,
            )
            return
        self._metrics.jobs_registered.add(1)

    async def cancel(self, event: CampaignCancelled, context: MessageContext) -> bool:
        """Снять кампанию с расписания.

        Отметка об отмене сохраняется даже при отсутствии расписания. Это
        защищает от порядка, когда campaign.cancelled обработан раньше
        campaign.scheduled.

        Returns:
            True, если расписание было изменено.
        """
        now = self._clock.now()
        changed = False
        async with self._uow_factory() as uow:
            await uow.cancellations.add(event.campaign_id, event.occurred_at)
            schedule = await uow.schedules.get(event.campaign_id)
            if schedule is None:
                logger.warning(
                    "Расписание кампании %s не найдено при отмене, отметка сохранена",
                    event.campaign_id,
                )
            elif schedule.cancel(now):
                await uow.schedules.save(schedule)
                await uow.outbox.add_audit(
                    _audit_event(
                        action=AuditAction.CAMPAIGN_CANCELLED,
                        campaign_id=event.campaign_id,
                        occurred_at=event.occurred_at,
                        details={"status": schedule.status.value},
                        context=context,
                    )
                )
                changed = True
            await uow.commit()
        await self._registrar.remove(event.campaign_id)
        return changed

    def _ensure_run_at_not_missed(self, schedule: ScheduleSpec, now: datetime) -> None:
        """Проверить, что разовый запуск еще можно выполнить.

        Raises:
            ValidationError: Время запуска вышло за пределы misfire grace.
        """
        if schedule.kind is not ScheduleKind.ONE_OFF:
            return
        run_at = schedule.run_at
        if run_at is None:
            raise ValidationError("Для one_off требуется run_at")
        threshold = now - timedelta(seconds=self._misfire_grace_seconds)
        if run_at < threshold:
            raise ValidationError("Время разового запуска уже прошло")


class ScheduleRecovery:
    """Восстанавливает задания активных расписаний после перезапуска."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registrar: JobRegistrar,
        trigger: CampaignTrigger,
        clock: Clock,
        metrics: Metrics,
    ) -> None:
        """Сохранить зависимости восстановления."""
        self._uow_factory = uow_factory
        self._registrar = registrar
        self._trigger = trigger
        self._clock = clock
        self._metrics = metrics
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        """Вернуть описание последней ошибки восстановления."""
        return self._last_error

    async def run(self) -> int:
        """Зарегистрировать все активные расписания и вернуть их число."""
        self._last_error = None
        async with self._uow_factory() as uow:
            schedules = await uow.schedules.list_active()
        recovered = 0
        for schedule in schedules:
            try:
                async with self._uow_factory() as uow:
                    cancelled_at = await uow.cancellations.get_occurred_at(schedule.campaign_id)
                    if cancelled_at is not None:
                        current = await uow.schedules.get(schedule.campaign_id)
                        if current is not None and current.cancel(self._clock.now()):
                            await uow.schedules.save(current)
                            await uow.commit()
                        logger.info(
                            "Задание кампании %s не восстановлено: кампания отменена",
                            schedule.campaign_id,
                        )
                        continue
                next_run_at = await self._registrar.register(schedule, self._trigger.execute)
                now = self._clock.now()
                async with self._uow_factory() as uow:
                    current = await uow.schedules.get(schedule.campaign_id)
                    if current is None:
                        continue
                    current.set_next_run(next_run_at, now=now)
                    await uow.schedules.save(current)
                    await uow.commit()
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._metrics.recovery_failures.add(1)
                logger.exception(
                    "Не удалось восстановить задание кампании %s",
                    schedule.campaign_id,
                )
                continue
            recovered += 1
        logger.info("Восстановлено заданий планировщика: %s", recovered)
        return recovered


def _audit_event(
    *,
    action: AuditAction,
    campaign_id: CampaignId,
    occurred_at: datetime,
    details: dict[str, str],
    context: MessageContext,
) -> AuditEvent:
    """Собрать audit-событие планировщика с детерминированным id."""
    return AuditEvent(
        event_id=AuditEventId(
            uuid5(AUDIT_NAMESPACE, f"{action.value}:{campaign_id}:{occurred_at.isoformat()}")
        ),
        occurred_at=occurred_at,
        service=SCHEDULER_SERVICE,
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier=SCHEDULER_SERVICE),
        action=action,
        entity_type=CAMPAIGN_ENTITY_TYPE,
        entity_id=str(campaign_id),
        campaign_id=campaign_id,
        outcome=AuditOutcome.SUCCESS,
        details=details,
        correlation_id=context.correlation_id,
        trace_id=context.trace_id,
    )


def _schedule_details(schedule: ScheduleSpec) -> dict[str, str]:
    """Описать расписание для audit-события."""
    return {
        "kind": schedule.kind.value,
        "timezone": schedule.timezone,
        "run_at": schedule.run_at.isoformat() if schedule.run_at is not None else "",
        "cron": schedule.cron or "",
    }


def _current_trace_id() -> str | None:
    """Вернуть идентификатор текущего OTel-трейса."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.trace_id, "032x")
