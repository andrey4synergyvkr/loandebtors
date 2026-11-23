"""Проверка миграций Audit Exporter в отдельной базе."""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url
from testcontainers.community.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_POSTGRES_IMAGE = "postgres:16-alpine"
_REPO_ROOT = Path(__file__).resolve().parents[5]
_CONNECT_ATTEMPTS = 10
_CONNECT_DELAY_SECONDS = 0.5


def _run_alembic(command: str, database_url: str) -> None:
    """Выполнить команду Alembic с заданным DSN."""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "source/services/audit_exporter/alembic.ini",
            *command.split(),
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Alembic {command} завершился ошибкой: {result.stdout}\n{result.stderr}")


@pytest.fixture(scope="module")
def postgres() -> Iterator[PostgresContainer]:
    """Поднять PostgreSQL для проверки миграций."""
    container: PostgresContainer | None = None
    try:
        container = PostgresContainer(_POSTGRES_IMAGE)
        container.start()
    except Exception as exc:
        with suppress(Exception):
            if container is not None:
                container.stop()
        pytest.skip(f"Docker или PostgreSQL недоступны: {exc}")
    assert container is not None
    try:
        yield container
    finally:
        with suppress(Exception):
            container.stop()


def _database_url(postgres: PostgresContainer, database: str) -> str:
    """Собрать async DSN для указанной базы."""
    base = postgres.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
    return make_url(base).set(database=database).render_as_string(hide_password=False)


def _asyncpg_dsn(url: str) -> str:
    """Преобразовать SQLAlchemy DSN в DSN asyncpg."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _connect(dsn: str) -> asyncpg.Connection:
    """Подключиться к PostgreSQL с повторами на время инициализации."""
    last_error: Exception | None = None
    for _ in range(_CONNECT_ATTEMPTS):
        try:
            return await asyncpg.connect(dsn)
        except (asyncpg.PostgresError, OSError) as exc:
            last_error = exc
            await asyncio.sleep(_CONNECT_DELAY_SECONDS)
    assert last_error is not None
    raise last_error


async def test_migrations_upgrade_downgrade_and_upgrade_again(
    postgres: PostgresContainer,
) -> None:
    """Миграции применяются повторно после downgrade base."""
    admin_url = _database_url(postgres, "postgres")
    database_name = f"audit_migration_{uuid.uuid4().hex[:12]}"
    database_url = _database_url(postgres, database_name)
    admin = await _connect(_asyncpg_dsn(admin_url))
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await admin.close()

    try:
        _run_alembic("upgrade head", database_url)
        _run_alembic("downgrade base", database_url)
        _run_alembic("upgrade head", database_url)

        connection = await _connect(_asyncpg_dsn(database_url))
        try:
            table = await connection.fetchval("SELECT to_regclass('audit.audit_record')")
            function = await connection.fetchval(
                "SELECT to_regprocedure('audit.reject_audit_record_mutation()')"
            )
        finally:
            await connection.close()

        assert table == "audit.audit_record"
        assert function is not None
    finally:
        admin = await _connect(_asyncpg_dsn(admin_url))
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        finally:
            await admin.close()
