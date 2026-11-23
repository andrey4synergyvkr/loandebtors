"""Адаптер планировщика APScheduler."""

import logging
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from apscheduler.job import Job
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from opentelemetry import trace

from scheduler.config import Settings
from scheduler.domain import (
    CampaignId,
    CampaignSchedule,
    ScheduleKind,
    ScheduleSpec,
    ValidationError,
)
from scheduler.ports.jobs import JobCallback

logger = logging.getLogger(__name__)

TRACER_NAME: str = "loandebtors.scheduler"
TRIGGER_SPAN_NAME: str = "scheduler.trigger"
CAMPAIGN_ID_ATTRIBUTE: str = "campaign.id"


class APSchedulerJobRegistrar:
    """Хранит задания в памяти и регистрирует их в APScheduler."""

    def __init__(self, settings: Settings) -> None:
        """Создать планировщик с часовым поясом из настроек."""
        self._scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.schedule_timezone))
        self._misfire_grace_seconds = settings.schedule_misfire_grace_seconds
        self._coalesce = settings.schedule_coalesce
        self._tracer = trace.get_tracer(TRACER_NAME)

    @property
    def is_running(self) -> bool:
        """Вернуть признак запущенного планировщика."""
        return bool(self._scheduler.running)

    def start(self) -> None:
        """Запустить планировщик."""
        if not self._scheduler.running:
            self._scheduler.start()

    def stop(self) -> None:
        """Остановить планировщик без ожидания заданий."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def validate(self, schedule: ScheduleSpec) -> None:
        """Проверить, что правило запуска поддерживается.

        Raises:
            ValidationError: Выражение cron или время запуска некорректны.
        """
        try:
            _build_trigger(schedule)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Некорректное расписание: {exc}") from exc

    async def register(self, schedule: CampaignSchedule, callback: JobCallback) -> datetime | None:
        """Идемпотентно зарегистрировать задание по кампании."""
        trigger = _build_trigger(schedule.schedule)
        job: Job = self._scheduler.add_job(
            _wrap_callback(self._tracer, schedule.campaign_id, callback),
            trigger,
            id=str(schedule.campaign_id),
            name=f"campaign:{schedule.campaign_id}",
            replace_existing=True,
            misfire_grace_time=self._misfire_grace_seconds,
            coalesce=self._coalesce,
            max_instances=1,
        )
        return cast(datetime | None, job.next_run_time)

    async def remove(self, campaign_id: CampaignId) -> None:
        """Снять задание, если оно существует."""
        try:
            self._scheduler.remove_job(str(campaign_id))
        except JobLookupError:
            return

    async def next_run_at(self, campaign_id: CampaignId) -> datetime | None:
        """Вернуть ближайший плановый запуск задания."""
        job: Job | None = self._scheduler.get_job(str(campaign_id))
        if job is None:
            return None
        return cast(datetime | None, job.next_run_time)


def _build_trigger(schedule: ScheduleSpec) -> BaseTrigger:
    """Собрать триггер APScheduler по доменному правилу запуска."""
    timezone = ZoneInfo(schedule.timezone)
    if schedule.kind is ScheduleKind.ONE_OFF:
        if schedule.run_at is None:
            raise ValueError("Для one_off требуется run_at")
        return DateTrigger(run_date=schedule.run_at, timezone=timezone)
    if schedule.cron is None:
        raise ValueError("Для cron требуется выражение cron")
    return CronTrigger.from_crontab(schedule.cron, timezone=timezone)


def _wrap_callback(tracer: Any, campaign_id: CampaignId, callback: JobCallback) -> Any:
    """Обернуть callback трейсом и логированием ошибок."""

    async def run() -> None:
        with tracer.start_as_current_span(TRIGGER_SPAN_NAME) as span:
            span.set_attribute(CAMPAIGN_ID_ATTRIBUTE, str(campaign_id))
            try:
                await callback(campaign_id)
            except Exception as exc:
                span.record_exception(exc)
                logger.exception("Задание кампании %s завершилось ошибкой", campaign_id)
                raise

    return run
