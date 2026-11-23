"""Интеграционная проверка хранения кампаний в PostgreSQL."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from notifications.adapters.persistence.models import OutboxRow, TemplateRow
from notifications.adapters.persistence.uow import SqlAlchemyUnitOfWorkFactory
from notifications.application.campaigns import (
    CampaignService,
    CreateCampaignCommand,
    UpdateCampaignCommand,
)
from notifications.application.common import RequestContext
from notifications.application.templates import CreateTemplateCommand, TemplateService
from notifications.domain import (
    EMAIL_CHANNEL,
    CampaignStatus,
    DebtorSelection,
    TemplateKey,
    TemplateStatus,
)
from notifications.infrastructure.clock import SystemClock

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[5]
_POSTGRES_IMAGE = "postgres:16-alpine"
_CONTEXT = RequestContext(correlation_id="integration-campaign", trace_id=None)


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
        with suppress(Exception):
            if postgres is not None:
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


async def _active_template(
    templates: TemplateService,
    key: str,
    version: int = 1,
) -> None:
    """Создать и активировать шаблон."""
    template = await templates.create_template(
        CreateTemplateCommand(
            key=key,
            version=version,
            description="Шаблон для интеграционных кампаний",
            required_variables=("debtor_name", "amount"),
        ),
        _CONTEXT,
    )
    await templates.update_status(template.key, template.version, TemplateStatus.ACTIVE, _CONTEXT)


def _campaign_command(key: str, name: str) -> CreateCampaignCommand:
    """Собрать команду создания кампании."""
    return CreateCampaignCommand(
        name=name,
        channel=EMAIL_CHANNEL,
        template_key=TemplateKey(key),
        template_version=1,
        selection=DebtorSelection(criteria={"min_days_overdue": "30"}),
    )


async def test_campaign_lifecycle_is_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Создание, чтение и изменение кампании сохраняются в базе."""
    templates, campaigns = _services(session_factory)
    key = "integration-campaign-lifecycle"
    await _active_template(templates, key)
    created = await campaigns.create_campaign(
        _campaign_command(key, "Интеграционная кампания"),
        _CONTEXT,
    )

    stored = await campaigns.get_campaign(created.id)
    updated = await campaigns.update_campaign(
        created.id,
        UpdateCampaignCommand(
            name="Обновленная кампания",
            template_key=None,
            template_version=None,
            selection=None,
        ),
        _CONTEXT,
    )
    page = await campaigns.list_campaigns(status=CampaignStatus.DRAFT, limit=10, offset=0)

    assert stored.status is CampaignStatus.DRAFT
    assert stored.name == "Интеграционная кампания"
    assert updated.name == "Обновленная кампания"
    assert any(campaign.id == created.id for campaign in page.items)


async def test_campaign_audit_events_are_committed_to_outbox(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Audit-события кампании попадают в outbox в той же транзакции."""
    templates, campaigns = _services(session_factory)
    key = "integration-campaign-audit"
    await _active_template(templates, key)
    created = await campaigns.create_campaign(
        _campaign_command(key, "Кампания с аудитом"),
        _CONTEXT,
    )
    await campaigns.update_campaign(
        created.id,
        UpdateCampaignCommand(
            name="Кампания с аудитом изменена",
            template_key=None,
            template_version=None,
            selection=None,
        ),
        _CONTEXT,
    )

    async with session_factory() as session:
        rows = (await session.scalars(select(OutboxRow).where(OutboxRow.event_type == "audit.event"))).all()

    relevant = [row for row in rows if row.payload.get("entity_id") == str(created.id)]
    assert len(relevant) == 2
    assert {row.payload["action"] for row in relevant} == {
        "campaign.created",
        "campaign.updated",
    }
    assert all(row.headers["correlation_id"] == "integration-campaign" for row in relevant)
    assert all(row.payload["campaign_id"] == str(created.id) for row in relevant)


async def test_template_with_campaign_cannot_be_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Внешний ключ не позволяет удалить шаблон, выбранный кампанией."""
    templates, campaigns = _services(session_factory)
    key = "integration-campaign-fk"
    await _active_template(templates, key)
    await campaigns.create_campaign(_campaign_command(key, "Кампания с ключом"), _CONTEXT)

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            await session.execute(delete(TemplateRow).where(TemplateRow.key == key))
            await session.commit()


async def test_campaign_references_existing_template(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Кампания сохраняет ссылку на версию шаблона."""
    templates, campaigns = _services(session_factory)
    key = "integration-campaign-reference"
    await _active_template(templates, key)
    created = await campaigns.create_campaign(
        _campaign_command(key, "Кампания со ссылкой"),
        _CONTEXT,
    )

    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT template_key, template_version FROM notification.campaigns "
                    "WHERE id = :campaign_id"
                ),
                {"campaign_id": created.id},
            )
        ).one()

    assert row.template_key == key
    assert row.template_version == 1
