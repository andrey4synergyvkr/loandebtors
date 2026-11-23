"""Интеграционная проверка запуска Notifications с зависимостями."""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import cast

import httpx
import pytest
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from notifications.adapters.http.constants import HEALTH_PATH
from notifications.application.health import (
    APPLICATION_CHECK_NAME,
    DATABASE_CHECK_NAME,
    MAINTENANCE_CHECK_NAME,
    OUTBOX_RELAY_CHECK_NAME,
    RABBITMQ_CHECK_NAME,
)

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[5]
_STARTUP_TIMEOUT_SECONDS = 90.0
_REQUEST_TIMEOUT_SECONDS = 5.0
_RABBITMQ_LOG_TIMEOUT_SECONDS = 60
_POSTGRES_IMAGE = "postgres:16-alpine"
_RABBITMQ_IMAGE = "rabbitmq:3.13-alpine"


def _free_port() -> int:
    """Найти свободный TCP-порт на localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(
    base_url: str,
    process: subprocess.Popen[str],
    timeout: float = _STARTUP_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Ждать полной готовности сервиса и вернуть health-ответ."""
    deadline = time.monotonic() + timeout
    last_error = "нет ответа"

    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout is not None else ""
            pytest.fail(f"Сервис завершился до healthcheck: {output}")

        try:
            response = httpx.get(f"{base_url}{HEALTH_PATH}", timeout=_REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 200:
                payload = response.json()
                checks = {check["name"]: check["status"] for check in payload["checks"]}
                expected = {
                    APPLICATION_CHECK_NAME,
                    DATABASE_CHECK_NAME,
                    RABBITMQ_CHECK_NAME,
                    OUTBOX_RELAY_CHECK_NAME,
                    MAINTENANCE_CHECK_NAME,
                }
                if expected.issubset(checks) and all(value == "ok" for value in checks.values()):
                    return cast(dict[str, object], payload)
                last_error = f"не все проверки готовы: {checks}"
            else:
                last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)

        time.sleep(0.3)

    pytest.fail(f"Healthcheck не прошел за {timeout} секунд: {last_error}")


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
def infrastructure() -> Iterator[tuple[str, str]]:
    """Поднять PostgreSQL и RabbitMQ и вернуть их DSN."""
    postgres: PostgresContainer | None = None
    rabbitmq: DockerContainer | None = None

    try:
        postgres = PostgresContainer(_POSTGRES_IMAGE)
        rabbitmq = (
            DockerContainer(_RABBITMQ_IMAGE)
            .with_env("RABBITMQ_DEFAULT_USER", "loandebtors")
            .with_env("RABBITMQ_DEFAULT_PASS", "loandebtors")
            .with_exposed_ports(5672)
        )
        postgres.start()
        rabbitmq.waiting_for(
            LogMessageWaitStrategy("Server startup complete").with_startup_timeout(
                _RABBITMQ_LOG_TIMEOUT_SECONDS
            )
        ).start()
    except Exception as exc:
        with suppress(Exception):
            if rabbitmq is not None:
                rabbitmq.stop()
        with suppress(Exception):
            if postgres is not None:
                postgres.stop()
        pytest.skip(f"Docker или тестовые контейнеры недоступны: {exc}")
    assert postgres is not None
    assert rabbitmq is not None

    database_url = postgres.get_connection_url().replace(
        "postgresql+psycopg2",
        "postgresql+asyncpg",
    )
    rabbitmq_url = (
        "amqp://loandebtors:loandebtors@"
        f"{rabbitmq.get_container_host_ip()}:{rabbitmq.get_exposed_port(5672)}/"
    )

    try:
        yield database_url, rabbitmq_url
    finally:
        with suppress(Exception):
            rabbitmq.stop()
        with suppress(Exception):
            postgres.stop()


@pytest.fixture
def notifications_url(infrastructure: tuple[str, str]) -> Iterator[str]:
    """Поднять uvicorn на свободном порту и вернуть базовый URL."""
    database_url, rabbitmq_url = infrastructure
    _apply_migrations(database_url)

    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "OTEL_ENABLED": "false",
            "ENVIRONMENT": "integration",
            "SERVICE_NAME": "notifications",
            "DATABASE_URL": database_url,
            "RABBITMQ_URL": rabbitmq_url,
            "CHECK_DEPENDENCIES": "true",
            "RUN_BACKGROUND_WORKERS": "true",
            "HEALTH_CHECK_TIMEOUT_SECONDS": "5",
        }
    )
    source_path = str(_REPO_ROOT / "source/services/notifications/src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{source_path}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else source_path
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "notifications.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        cwd=_REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"

    try:
        _wait_for_health(base_url, process)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_service_starts_with_dependencies_and_returns_health(notifications_url: str) -> None:
    """Сервис поднимается с PostgreSQL и RabbitMQ и отдаёт полный health."""
    response = httpx.get(
        f"{notifications_url}{HEALTH_PATH}",
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "notifications"
    assert payload["version"]
    assert payload["uptime_seconds"] >= 0
    checks = {check["name"]: check["status"] for check in payload["checks"]}
    assert checks[APPLICATION_CHECK_NAME] == "ok"
    assert checks[DATABASE_CHECK_NAME] == "ok"
    assert checks[RABBITMQ_CHECK_NAME] == "ok"
    assert checks[OUTBOX_RELAY_CHECK_NAME] == "ok"
    assert checks[MAINTENANCE_CHECK_NAME] == "ok"
