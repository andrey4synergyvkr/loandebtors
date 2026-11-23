"""Интеграционная проверка хранения шаблонов в PostgreSQL."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from notifications.adapters.persistence.models import OutboxRow
from notifications.adapters.persistence.uow import SqlAlchemyUnitOfWorkFactory
from notifications.application.common import RequestContext
from notifications.application.templates import (
    CreateTemplateCommand,
    TemplateService,
)
from notifications.domain import TemplateKey, TemplateStatus
from notifications.infrastructure.clock import SystemClock

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[5]
_POSTGRES_IMAGE = "postgres:16-alpine"
_CONTEXT = RequestContext(correlation_id="integration", trace_id=None)


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


def _service(session_factory: async_sessionmaker[AsyncSession]) -> TemplateService:
    """Собрать сервис шаблонов поверх тестовой базы."""
    return TemplateService(
        uow_factory=SqlAlchemyUnitOfWorkFactory(session_factory),
        clock=SystemClock(),
    )


def _command(key: str, version: int) -> CreateTemplateCommand:
    """Собрать команду создания шаблона."""
    return CreateTemplateCommand(
        key=key,
        version=version,
        description="Интеграционный шаблон",
        required_variables=("debtor_name", "amount"),
    )


async def test_template_lifecycle_is_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Создание и активация версий сохраняются в базе."""
    service = _service(session_factory)
    key = TemplateKey("integration-lifecycle")
    await service.create_template(_command("integration-lifecycle", 1), _CONTEXT)
    await service.create_template(_command("integration-lifecycle", 2), _CONTEXT)
    await service.update_status(key, 1, TemplateStatus.ACTIVE, _CONTEXT)
    await service.update_status(key, 2, TemplateStatus.ACTIVE, _CONTEXT)

    current = await service.get_template(key)
    previous = await service.get_template(key, 1)
    page = await service.list_templates(status=None, limit=10, offset=0)

    assert current.version == 2
    assert current.status is TemplateStatus.ACTIVE
    assert previous.status is TemplateStatus.ARCHIVED
    assert any(template.key == key for template in page.items)


async def test_audit_events_are_committed_to_outbox(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Audit-события шаблонов попадают в outbox в той же транзакции."""
    service = _service(session_factory)
    key = "integration-audit"
    await service.create_template(_command(key, 1), _CONTEXT)
    await service.update_status(
        TemplateKey(key),
        1,
        TemplateStatus.ACTIVE,
        _CONTEXT,
    )

    async with session_factory() as session:
        rows = (await session.scalars(select(OutboxRow).where(OutboxRow.event_type == "audit.event"))).all()

    relevant = [row for row in rows if str(row.payload.get("entity_id", "")).startswith(f"{key}:")]
    assert relevant
    assert all(row.exchange == "loan-debtors.events" for row in relevant)
    assert all(row.routing_key == "audit.event" for row in relevant)
    assert all(row.headers["correlation_id"] == "integration" for row in relevant)
    assert {row.payload["action"] for row in relevant} == {
        "template.created",
        "template.status.changed",
    }


async def test_database_rejects_two_active_versions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Уникальный частичный индекс не допускает две активные версии."""
    service = _service(session_factory)
    key = "integration-unique"
    await service.create_template(_command(key, 1), _CONTEXT)
    await service.create_template(_command(key, 2), _CONTEXT)
    await service.update_status(TemplateKey(key), 1, TemplateStatus.ACTIVE, _CONTEXT)
    await service.update_status(TemplateKey(key), 2, TemplateStatus.ACTIVE, _CONTEXT)

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE notification.templates SET status = 'active' WHERE key = :key AND version = 1"),
                {"key": key},
            )
            await session.commit()
