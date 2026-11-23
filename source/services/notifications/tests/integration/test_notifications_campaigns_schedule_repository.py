"""Интеграционная проверка планирования и отмены кампаний."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from notifications.adapters.persistence.models import OutboxRow
from notifications.adapters.persistence.uow import SqlAlchemyUnitOfWorkFactory
from notifications.application.campaigns import CampaignService, CreateCampaignCommand
from notifications.application.common import RequestContext
from notifications.application.templates import CreateTemplateCommand, TemplateService
from notifications.domain import (
    EMAIL_CHANNEL,
    Campaign,
    CampaignStatus,
    DebtorSelection,
    ScheduleKind,
    ScheduleSpec,
    TemplateKey,
    TemplateStatus,
)
from notifications.infrastructure.clock import SystemClock

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[5]
_POSTGRES_IMAGE = "postgres:16-alpine"
_CONTEXT = RequestContext(correlation_id="integration-schedule", trace_id=None)


def _apply_migrations(database_url: str) -> None:
    """Применить миграции Notifications к тестовой базе."""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "source/services/notifications/alembic.ini",
            "upgrade",
            "head",
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Миграции не применились: {result.stdout}\n{result.stderr}")


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """Поднять PostgreSQL и применить миграции."""
    postgres: PostgresContainer | None = None
    try:
        postgres = PostgresContainer(_POSTGRES_IMAGE)
        postgres.start()
    except Exception as exc:
        if postgres is not None:
            with suppress(Exception):
                postgres.stop()
        pytest.skip(f"Docker или PostgreSQL недоступны: {exc}")

    assert postgres is not None
    url = postgres.get_connection_url().replace(
        "postgresql+psycopg2",
        "postgresql+asyncpg",
    )
    try:
        _apply_migrations(url)
        yield url
    finally:
        with suppress(Exception):
            postgres.stop()


@pytest.fixture
async def session_factory(
    database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Создать фабрику сессий к тестовой базе."""
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _services(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[TemplateService, CampaignService]:
    """Собрать сервисы шаблонов и кампаний поверх тестовой базы."""
    uow_factory = SqlAlchemyUnitOfWorkFactory(session_factory)
    clock = SystemClock()
    return (
        TemplateService(uow_factory=uow_factory, clock=clock),
        CampaignService(uow_factory=uow_factory, clock=clock),
    )


async def _active_template(templates: TemplateService, key: str) -> None:
    """Создать и активировать шаблон."""
    template = await templates.create_template(
        CreateTemplateCommand(
            key=key,
            version=1,
            description="Шаблон для интеграционного расписания",
            required_variables=("debtor_name",),
        ),
        _CONTEXT,
    )
    await templates.update_status(template.key, template.version, TemplateStatus.ACTIVE, _CONTEXT)


async def _draft_campaign(campaigns: CampaignService, key: str, name: str) -> Campaign:
    """Создать draft-кампанию."""
    return await campaigns.create_campaign(
        CreateCampaignCommand(
            name=name,
            channel=EMAIL_CHANNEL,
            template_key=TemplateKey(key),
            template_version=1,
            selection=DebtorSelection(criteria={"min_days_overdue": "30"}),
        ),
        _CONTEXT,
    )


def _one_off() -> ScheduleSpec:
    """Собрать разовое расписание в будущем."""
    return ScheduleSpec(
        kind=ScheduleKind.ONE_OFF,
        timezone="Europe/Moscow",
        run_at=datetime.now(UTC) + timedelta(days=1),
    )


async def test_schedule_and_cancel_are_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Статусы и расписание сохраняются в базе."""
    templates, campaigns = _services(session_factory)
    key = "integration-schedule-lifecycle"
    await _active_template(templates, key)
    campaign = await _draft_campaign(campaigns, key, "Кампания для расписания")

    scheduled = await campaigns.schedule_campaign(campaign.id, _one_off(), _CONTEXT)
    stored_scheduled = await campaigns.get_campaign(campaign.id)
    cancelled = await campaigns.cancel_campaign(campaign.id, _CONTEXT)
    stored_cancelled = await campaigns.get_campaign(campaign.id)

    assert scheduled.status is CampaignStatus.SCHEDULED
    assert stored_scheduled.schedule is not None
    assert stored_scheduled.schedule.kind is ScheduleKind.ONE_OFF
    assert stored_scheduled.schedule.timezone == "Europe/Moscow"
    assert stored_scheduled.scheduled_at is not None
    assert cancelled.status is CampaignStatus.CANCELLED
    assert cancelled.cancelled_at is not None
    assert cancelled.finished_at is not None
    assert stored_cancelled.status is CampaignStatus.CANCELLED


async def test_cron_schedule_is_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cron-выражение сохраняется в JSONB."""
    templates, campaigns = _services(session_factory)
    key = "integration-schedule-cron"
    await _active_template(templates, key)
    campaign = await _draft_campaign(campaigns, key, "Кампания с cron")

    await campaigns.schedule_campaign(
        campaign.id,
        ScheduleSpec(
            kind=ScheduleKind.CRON,
            timezone="Europe/Moscow",
            cron="0 10 * * 1-5",
        ),
        _CONTEXT,
    )

    stored = await campaigns.get_campaign(campaign.id)
    assert stored.schedule is not None
    assert stored.schedule.kind is ScheduleKind.CRON
    assert stored.schedule.cron == "0 10 * * 1-5"


async def test_schedule_and_cancel_write_outbox_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """В outbox попадают campaign.scheduled и campaign.cancelled."""
    templates, campaigns = _services(session_factory)
    key = "integration-schedule-outbox"
    await _active_template(templates, key)
    campaign = await _draft_campaign(campaigns, key, "Кампания с событиями")
    await campaigns.schedule_campaign(campaign.id, _one_off(), _CONTEXT)
    await campaigns.cancel_campaign(campaign.id, _CONTEXT)

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(OutboxRow).where(
                    OutboxRow.event_type.in_(["campaign.scheduled", "campaign.cancelled"])
                )
            )
        ).all()

    relevant = {row.event_type: row for row in rows if row.payload.get("campaign_id") == str(campaign.id)}
    assert set(relevant) == {"campaign.scheduled", "campaign.cancelled"}
    scheduled = relevant["campaign.scheduled"]
    assert scheduled.exchange == "loan-debtors.events"
    assert scheduled.routing_key == "campaign.scheduled"
    assert scheduled.payload["schedule"]["kind"] == "one_off"
    assert scheduled.payload["schedule"]["timezone"] == "Europe/Moscow"
    assert all(row.headers["correlation_id"] == "integration-schedule" for row in relevant.values())
