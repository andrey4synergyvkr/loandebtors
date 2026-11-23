"""Проверка адаптера APScheduler."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from scheduler.adapters.scheduling.registrar import APSchedulerJobRegistrar
from scheduler.config import Settings
from scheduler.domain import (
    CampaignId,
    CampaignSchedule,
    ScheduleKind,
    ScheduleSpec,
    ValidationError,
)

CAMPAIGN_ID = CampaignId(UUID("3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"))
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


async def _noop(campaign_id: CampaignId) -> None:
    """Пустой callback задания."""


def _registrar() -> APSchedulerJobRegistrar:
    """Создать адаптер с тестовыми настройками."""
    return APSchedulerJobRegistrar(
        Settings(
            otel_enabled=False,
            schedule_timezone="Europe/Moscow",
            schedule_misfire_grace_seconds=60,
            schedule_coalesce=True,
        )
    )


async def test_validate_accepts_supported_specs() -> None:
    """Разовое и корректное cron-расписание проходят проверку."""
    registrar = _registrar()

    await registrar.validate(ScheduleSpec(kind=ScheduleKind.ONE_OFF, timezone="Europe/Moscow", run_at=NOW))
    await registrar.validate(
        ScheduleSpec(kind=ScheduleKind.CRON, timezone="Europe/Moscow", cron="0 10 * * 1-5")
    )


async def test_validate_rejects_invalid_cron_values() -> None:
    """Некорректные значения cron отклоняются доменной ошибкой."""
    registrar = _registrar()

    with pytest.raises(ValidationError):
        await registrar.validate(
            ScheduleSpec(kind=ScheduleKind.CRON, timezone="Europe/Moscow", cron="99 99 * * *")
        )


async def test_register_remove_and_next_run() -> None:
    """Задание идемпотентно регистрируется и снимается."""
    registrar = _registrar()
    registrar.start()
    try:
        run_at = NOW + timedelta(hours=1)
        schedule = CampaignSchedule.create(
            CAMPAIGN_ID,
            ScheduleSpec(kind=ScheduleKind.ONE_OFF, timezone="Europe/Moscow", run_at=run_at),
            NOW,
        )

        next_run_at = await registrar.register(schedule, _noop)

        assert next_run_at is not None
        assert registrar.is_running is True
        assert await registrar.next_run_at(CAMPAIGN_ID) == next_run_at
        await registrar.register(schedule, _noop)
        assert await registrar.next_run_at(CAMPAIGN_ID) == next_run_at
        await registrar.remove(CAMPAIGN_ID)
        assert await registrar.next_run_at(CAMPAIGN_ID) is None
    finally:
        registrar.stop()
