"""Проверка сценариев расписания, срабатывания и восстановления."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_scheduler_fakes import (
    FakeClock,
    FakeJobRegistrar,
    FakeUnitOfWorkFactory,
    InMemoryCancelledCampaignRepository,
    InMemoryScheduleRepository,
    RecordingOutbox,
)

from scheduler.application.common import MessageContext
from scheduler.application.scheduling import (
    CampaignTrigger,
    ScheduleRecovery,
    ScheduleService,
)
from scheduler.domain import (
    AuditAction,
    CampaignCancelled,
    CampaignId,
    CampaignSchedule,
    CampaignScheduled,
    ScheduleKind,
    ScheduleSpec,
    ScheduleStatus,
    ValidationError,
)
from scheduler.infrastructure.metrics import Metrics

CAMPAIGN_ID = CampaignId(UUID("3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"))
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
CONTEXT = MessageContext(correlation_id="corr-1", trace_id=None)


@dataclass(slots=True)
class Harness:
    """Набор зависимостей одного сценария."""

    repository: InMemoryScheduleRepository
    cancellations: InMemoryCancelledCampaignRepository
    outbox: RecordingOutbox
    registrar: FakeJobRegistrar
    clock: FakeClock
    trigger: CampaignTrigger
    service: ScheduleService
    recovery: ScheduleRecovery


def _harness(now: datetime = NOW) -> Harness:
    """Собрать сценарии на тестовых двойниках."""
    repository = InMemoryScheduleRepository()
    cancellations = InMemoryCancelledCampaignRepository()
    outbox = RecordingOutbox()
    registrar = FakeJobRegistrar()
    clock = FakeClock(current=now)
    metrics = Metrics()
    uow_factory = FakeUnitOfWorkFactory(repository, cancellations, outbox)
    trigger = CampaignTrigger(
        uow_factory=uow_factory,
        registrar=registrar,
        clock=clock,
        metrics=metrics,
    )
    service = ScheduleService(
        uow_factory=uow_factory,
        registrar=registrar,
        clock=clock,
        metrics=metrics,
        trigger=trigger,
        misfire_grace_seconds=60,
    )
    recovery = ScheduleRecovery(
        uow_factory=uow_factory,
        registrar=registrar,
        trigger=trigger,
        clock=clock,
        metrics=metrics,
    )
    return Harness(
        repository=repository,
        cancellations=cancellations,
        outbox=outbox,
        registrar=registrar,
        clock=clock,
        trigger=trigger,
        service=service,
        recovery=recovery,
    )


def _one_off(run_at: datetime = NOW + timedelta(hours=1)) -> ScheduleSpec:
    """Вернуть разовое расписание."""
    return ScheduleSpec(kind=ScheduleKind.ONE_OFF, timezone="Europe/Moscow", run_at=run_at)


def _cron(expression: str = "0 10 * * 1-5") -> ScheduleSpec:
    """Вернуть cron-расписание."""
    return ScheduleSpec(kind=ScheduleKind.CRON, timezone="Europe/Moscow", cron=expression)


async def test_schedule_creates_job_and_audit() -> None:
    """Команда campaign.scheduled сохраняет расписание и пишет аудит."""
    harness = _harness()
    run_at = NOW + timedelta(hours=2)

    await harness.service.schedule(
        CampaignScheduled(campaign_id=CAMPAIGN_ID, schedule=_one_off(run_at), occurred_at=NOW),
        CONTEXT,
    )

    stored = await harness.repository.get(CAMPAIGN_ID)
    assert stored is not None
    assert stored.status is ScheduleStatus.ACTIVE
    assert stored.next_run_at == run_at
    assert stored.correlation_id == "corr-1"
    assert CAMPAIGN_ID in harness.registrar.registrations
    assert [event.action for event in harness.outbox.audit_events] == [AuditAction.CAMPAIGN_SCHEDULED]


async def test_schedule_updates_existing_schedule() -> None:
    """Повторная команда заменяет правило запуска существующего расписания."""
    harness = _harness()
    await harness.service.schedule(
        CampaignScheduled(campaign_id=CAMPAIGN_ID, schedule=_cron(), occurred_at=NOW),
        CONTEXT,
    )
    next_context = MessageContext(correlation_id="corr-2", trace_id="trace-2")

    await harness.service.schedule(
        CampaignScheduled(
            campaign_id=CAMPAIGN_ID,
            schedule=_one_off(NOW + timedelta(hours=3)),
            occurred_at=NOW + timedelta(minutes=1),
        ),
        next_context,
    )

    stored = await harness.repository.get(CAMPAIGN_ID)
    assert stored is not None
    assert stored.schedule.kind is ScheduleKind.ONE_OFF
    assert stored.correlation_id == "corr-2"
    assert harness.outbox.audit_events[-1].action is AuditAction.CAMPAIGN_SCHEDULED


async def test_schedule_rejects_missed_one_off() -> None:
    """Разовый запуск старше misfire grace отклоняется."""
    harness = _harness()

    with pytest.raises(ValidationError):
        await harness.service.schedule(
            CampaignScheduled(
                campaign_id=CAMPAIGN_ID,
                schedule=_one_off(NOW - timedelta(minutes=5)),
                occurred_at=NOW,
            ),
            CONTEXT,
        )

    assert await harness.repository.get(CAMPAIGN_ID) is None


async def test_schedule_rejects_unsupported_expression() -> None:
    """Ошибка проверки планировщика не сохраняет расписание."""
    harness = _harness()
    harness.registrar.validate_error = "неподдерживаемое выражение"

    with pytest.raises(ValidationError):
        await harness.service.schedule(
            CampaignScheduled(campaign_id=CAMPAIGN_ID, schedule=_cron(), occurred_at=NOW),
            CONTEXT,
        )

    assert await harness.repository.get(CAMPAIGN_ID) is None


async def test_cancel_removes_job_and_writes_audit() -> None:
    """Отмена снимает задание и переводит расписание в cancelled."""
    harness = _harness()
    await harness.service.schedule(
        CampaignScheduled(campaign_id=CAMPAIGN_ID, schedule=_cron(), occurred_at=NOW),
        CONTEXT,
    )

    changed = await harness.service.cancel(
        CampaignCancelled(campaign_id=CAMPAIGN_ID, occurred_at=NOW + timedelta(minutes=1)),
        CONTEXT,
    )

    stored = await harness.repository.get(CAMPAIGN_ID)
    assert changed is True
    assert stored is not None
    assert stored.status is ScheduleStatus.CANCELLED
    assert stored.next_run_at is None
    assert CAMPAIGN_ID in harness.registrar.removed
    assert harness.outbox.audit_events[-1].action is AuditAction.CAMPAIGN_CANCELLED


async def test_cancel_unknown_schedule_is_idempotent() -> None:
    """Отмена неизвестного расписания не пишет аудит и сохраняет отметку."""
    harness = _harness()

    changed = await harness.service.cancel(
        CampaignCancelled(campaign_id=CAMPAIGN_ID, occurred_at=NOW),
        CONTEXT,
    )

    assert changed is False
    assert harness.outbox.audit_events == []
    assert await harness.cancellations.get_occurred_at(CAMPAIGN_ID) == NOW


async def test_cancel_before_schedule_blocks_job_registration() -> None:
    """Отмена, пришедшая раньше расписания, не дает зарегистрировать задание."""
    harness = _harness()

    await harness.service.cancel(
        CampaignCancelled(campaign_id=CAMPAIGN_ID, occurred_at=NOW),
        CONTEXT,
    )
    await harness.service.schedule(
        CampaignScheduled(
            campaign_id=CAMPAIGN_ID,
            schedule=_one_off(NOW + timedelta(hours=1)),
            occurred_at=NOW + timedelta(seconds=1),
        ),
        CONTEXT,
    )

    assert CAMPAIGN_ID not in harness.registrar.registrations
    assert await harness.repository.get(CAMPAIGN_ID) is None
    assert all(event.action is not AuditAction.CAMPAIGN_SCHEDULED for event in harness.outbox.audit_events)


async def test_repeated_cancel_writes_audit_once() -> None:
    """Повторная отмена не создает второе audit-событие."""
    harness = _harness()
    await harness.service.schedule(
        CampaignScheduled(campaign_id=CAMPAIGN_ID, schedule=_cron(), occurred_at=NOW),
        CONTEXT,
    )
    event = CampaignCancelled(campaign_id=CAMPAIGN_ID, occurred_at=NOW)
    await harness.service.cancel(event, CONTEXT)
    audits_after_first = len(harness.outbox.audit_events)

    changed = await harness.service.cancel(event, CONTEXT)

    assert changed is False
    assert len(harness.outbox.audit_events) == audits_after_first


async def test_trigger_one_off_publishes_start_and_completes() -> None:
    """Срабатывание разового задания публикует campaign.start и завершает расписание."""
    harness = _harness()
    run_at = NOW + timedelta(hours=1)
    await harness.service.schedule(
        CampaignScheduled(campaign_id=CAMPAIGN_ID, schedule=_one_off(run_at), occurred_at=NOW),
        CONTEXT,
    )
    harness.clock.current = run_at

    await harness.trigger.execute(CAMPAIGN_ID)

    stored = await harness.repository.get(CAMPAIGN_ID)
    assert stored is not None
    assert stored.status is ScheduleStatus.COMPLETED
    assert stored.last_triggered_at == run_at
    start, correlation_id, _ = harness.outbox.campaign_starts[-1]
    assert start.campaign_id == CAMPAIGN_ID
    assert start.scheduled_for == run_at
    assert correlation_id == "corr-1"
    assert harness.outbox.audit_events[-1].action is AuditAction.CAMPAIGN_STARTED


async def test_trigger_cron_keeps_next_run() -> None:
    """Cron-задание после срабатывания остается активным."""
    harness = _harness()
    next_run_at = NOW + timedelta(days=1)
    harness.registrar.next_runs[CAMPAIGN_ID] = next_run_at
    await harness.service.schedule(
        CampaignScheduled(campaign_id=CAMPAIGN_ID, schedule=_cron(), occurred_at=NOW),
        CONTEXT,
    )

    await harness.trigger.execute(CAMPAIGN_ID)

    stored = await harness.repository.get(CAMPAIGN_ID)
    assert stored is not None
    assert stored.status is ScheduleStatus.ACTIVE
    assert stored.next_run_at == next_run_at
    assert len(harness.outbox.campaign_starts) == 1


async def test_trigger_cancelled_schedule_does_nothing() -> None:
    """Срабатывание снятого задания не публикует campaign.start."""
    harness = _harness()
    await harness.service.schedule(
        CampaignScheduled(campaign_id=CAMPAIGN_ID, schedule=_cron(), occurred_at=NOW),
        CONTEXT,
    )
    await harness.service.cancel(
        CampaignCancelled(campaign_id=CAMPAIGN_ID, occurred_at=NOW),
        CONTEXT,
    )
    harness.outbox.campaign_starts.clear()

    await harness.trigger.execute(CAMPAIGN_ID)

    assert harness.outbox.campaign_starts == []
    assert CAMPAIGN_ID in harness.registrar.removed


async def test_trigger_honours_tombstone_when_schedule_still_active() -> None:
    """Срабатывание видит отметку отмены даже при активной строке расписания."""
    harness = _harness()
    await harness.service.schedule(
        CampaignScheduled(campaign_id=CAMPAIGN_ID, schedule=_cron(), occurred_at=NOW),
        CONTEXT,
    )
    harness.outbox.campaign_starts.clear()
    await harness.cancellations.add(CAMPAIGN_ID, NOW + timedelta(minutes=1))

    await harness.trigger.execute(CAMPAIGN_ID)

    stored = await harness.repository.get(CAMPAIGN_ID)
    assert stored is not None
    assert stored.status is ScheduleStatus.CANCELLED
    assert harness.outbox.campaign_starts == []
    assert CAMPAIGN_ID in harness.registrar.removed


async def test_recovery_registers_active_schedules() -> None:
    """Восстановление регистрирует активные расписания и сохраняет next_run."""
    harness = _harness()
    schedule = CampaignSchedule.create(CAMPAIGN_ID, _cron(), NOW, correlation_id="corr-1")
    await harness.repository.save(schedule)
    next_run_at = NOW + timedelta(hours=5)
    harness.registrar.next_runs[CAMPAIGN_ID] = next_run_at

    recovered = await harness.recovery.run()

    stored = await harness.repository.get(CAMPAIGN_ID)
    assert recovered == 1
    assert CAMPAIGN_ID in harness.registrar.registrations
    assert stored is not None
    assert stored.next_run_at == next_run_at
    assert harness.recovery.last_error is None


async def test_recovery_skips_schedule_with_cancellation_tombstone() -> None:
    """Восстановление не регистрирует задание отмененной кампании."""
    harness = _harness()
    schedule = CampaignSchedule.create(CAMPAIGN_ID, _cron(), NOW, correlation_id="corr-1")
    await harness.repository.save(schedule)
    await harness.cancellations.add(CAMPAIGN_ID, NOW + timedelta(minutes=1))

    recovered = await harness.recovery.run()

    stored = await harness.repository.get(CAMPAIGN_ID)
    assert recovered == 0
    assert CAMPAIGN_ID not in harness.registrar.registrations
    assert stored is not None
    assert stored.status is ScheduleStatus.CANCELLED


async def test_recovery_records_registration_error() -> None:
    """Ошибка регистрации задания не прерывает восстановление."""
    harness = _harness()
    schedule = CampaignSchedule.create(
        CampaignId(uuid4()),
        _cron(),
        NOW,
        correlation_id="corr-1",
    )
    await harness.repository.save(schedule)
    harness.registrar.register_error = RuntimeError("планировщик недоступен")

    recovered = await harness.recovery.run()

    assert recovered == 0
    assert harness.recovery.last_error is not None
    assert "RuntimeError" in harness.recovery.last_error
