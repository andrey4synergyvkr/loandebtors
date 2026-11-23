"""Тестовые двойники портов Scheduler."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Self

from scheduler.domain import (
    AuditEvent,
    CampaignId,
    CampaignSchedule,
    CampaignStart,
    ScheduleSpec,
    ScheduleStatus,
    ValidationError,
)
from scheduler.ports.jobs import JobCallback
from scheduler.ports.outbox import EventOutbox
from scheduler.ports.repositories import CampaignScheduleRepository, CancelledCampaignRepository
from scheduler.ports.uow import UnitOfWork


@dataclass(slots=True)
class FakeClock:
    """Часы с управляемым текущим временем."""

    current: datetime

    def now(self) -> datetime:
        """Вернуть текущее время."""
        return self.current


@dataclass(slots=True)
class InMemoryScheduleRepository:
    """Репозиторий расписаний в памяти."""

    schedules: dict[CampaignId, CampaignSchedule] = field(default_factory=dict)

    async def get(self, campaign_id: CampaignId) -> CampaignSchedule | None:
        """Вернуть расписание или None."""
        schedule = self.schedules.get(campaign_id)
        return deepcopy(schedule) if schedule is not None else None

    async def save(self, schedule: CampaignSchedule) -> None:
        """Сохранить копию расписания."""
        self.schedules[schedule.campaign_id] = deepcopy(schedule)

    async def list_active(self) -> list[CampaignSchedule]:
        """Вернуть активные расписания."""
        return [
            deepcopy(schedule)
            for schedule in self.schedules.values()
            if schedule.status is ScheduleStatus.ACTIVE
        ]


@dataclass(slots=True)
class InMemoryCancelledCampaignRepository:
    """Репозиторий отметок об отмене в памяти."""

    occurred_at: dict[CampaignId, datetime] = field(default_factory=dict)

    async def add(self, campaign_id: CampaignId, occurred_at: datetime) -> None:
        """Идемпотентно сохранить время отмены."""
        self.occurred_at.setdefault(campaign_id, occurred_at)

    async def get_occurred_at(self, campaign_id: CampaignId) -> datetime | None:
        """Вернуть время отмены или None."""
        return self.occurred_at.get(campaign_id)


@dataclass(slots=True)
class RecordingOutbox:
    """Запоминает добавленные события outbox."""

    campaign_starts: list[tuple[CampaignStart, str, str | None]] = field(default_factory=list)
    audit_events: list[AuditEvent] = field(default_factory=list)

    async def add_campaign_start(
        self,
        event: CampaignStart,
        *,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Запомнить команду campaign.start."""
        self.campaign_starts.append((event, correlation_id, trace_id))

    async def add_audit(self, event: AuditEvent) -> None:
        """Запомнить audit-событие."""
        self.audit_events.append(event)


class FakeUnitOfWork:
    """Единица работы поверх репозитория и outbox в памяти."""

    schedules: CampaignScheduleRepository
    cancellations: CancelledCampaignRepository
    outbox: EventOutbox

    def __init__(
        self,
        repository: InMemoryScheduleRepository,
        cancellations: InMemoryCancelledCampaignRepository,
        outbox: RecordingOutbox,
    ) -> None:
        """Сохранить общие хранилища теста."""
        self.schedules = repository
        self.cancellations = cancellations
        self.outbox = outbox
        self.commits = 0

    async def __aenter__(self) -> Self:
        """Открыть единицу работы."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Закрыть единицу работы без дополнительных действий."""

    async def commit(self) -> None:
        """Зафиксировать изменения."""
        self.commits += 1


class FakeUnitOfWorkFactory:
    """Создаёт единицы работы с общими хранилищами."""

    def __init__(
        self,
        repository: InMemoryScheduleRepository,
        cancellations: InMemoryCancelledCampaignRepository,
        outbox: RecordingOutbox,
    ) -> None:
        """Сохранить общие хранилища теста."""
        self.repository = repository
        self.cancellations = cancellations
        self.outbox = outbox
        self.created: list[FakeUnitOfWork] = []

    def __call__(self) -> UnitOfWork:
        """Вернуть новую единицу работы."""
        uow = FakeUnitOfWork(self.repository, self.cancellations, self.outbox)
        self.created.append(uow)
        return uow


class FakeJobRegistrar:
    """Регистратор заданий без реального планировщика."""

    def __init__(self) -> None:
        """Создать пустой регистратор."""
        self.registrations: dict[CampaignId, tuple[CampaignSchedule, JobCallback]] = {}
        self.next_runs: dict[CampaignId, datetime | None] = {}
        self.removed: list[CampaignId] = []
        self.validate_error: str | None = None
        self.register_error: Exception | None = None

    async def validate(self, schedule: ScheduleSpec) -> None:
        """Проверить расписание или поднять заданную ошибку."""
        if self.validate_error is not None:
            raise ValidationError(self.validate_error)

    async def register(self, schedule: CampaignSchedule, callback: JobCallback) -> datetime | None:
        """Запомнить регистрацию задания."""
        if self.register_error is not None:
            raise self.register_error
        self.registrations[schedule.campaign_id] = (deepcopy(schedule), callback)
        if schedule.campaign_id not in self.next_runs:
            self.next_runs[schedule.campaign_id] = schedule.schedule.run_at
        return self.next_runs[schedule.campaign_id]

    async def remove(self, campaign_id: CampaignId) -> None:
        """Запомнить снятие задания."""
        self.removed.append(campaign_id)
        self.registrations.pop(campaign_id, None)

    async def next_run_at(self, campaign_id: CampaignId) -> datetime | None:
        """Вернуть заданное следующее срабатывание."""
        return self.next_runs.get(campaign_id)
