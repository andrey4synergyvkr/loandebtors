"""Общие фикстуры интеграционных тестов Audit Exporter."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO, cast

import httpx
import pytest
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

_STARTUP_TIMEOUT_SECONDS = 90.0
_REQUEST_TIMEOUT_SECONDS = 5.0
_RABBITMQ_LOG_TIMEOUT_SECONDS = 60
_POSTGRES_IMAGE = "postgres:16-alpine"
_RABBITMQ_IMAGE = "rabbitmq:3.13-alpine"
_HEALTH_PATH = "/health"
_AUDIT_EXPORTER_CHECKS = {"application", "database", "rabbitmq", "audit_consumer"}
_OUTBOX_CHECKS = {"application", "database", "rabbitmq", "outbox_relay"}
_EMAIL_CHANNEL_CHECKS = _OUTBOX_CHECKS | {"email_consumer"}
_REPO_ROOT = Path(__file__).resolve().parents[5]


def _free_port() -> int:
    """Найти свободный TCP-порт на localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(
    base_url: str,
    process: subprocess.Popen[str],
    log_file: IO[str],
    expected_checks: set[str],
    timeout: float = _STARTUP_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Ждать полной готовности сервиса и вернуть health-ответ."""
    deadline = time.monotonic() + timeout
    last_error = "нет ответа"

    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_file.flush()
            log_file.seek(0)
            pytest.fail(f"Сервис завершился до healthcheck: {log_file.read()}")

        try:
            response = httpx.get(f"{base_url}{_HEALTH_PATH}", timeout=_REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 200:
                payload = response.json()
                checks = {check["name"]: check["status"] for check in payload["checks"]}
                if expected_checks.issubset(checks) and all(value == "ok" for value in checks.values()):
                    return cast(dict[str, object], payload)
                last_error = f"не все проверки готовы: {checks}"
            else:
                last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)

        time.sleep(0.3)

    pytest.fail(f"Healthcheck не прошел за {timeout} секунд: {last_error}")


def _apply_migrations(service: str, database_url: str) -> None:
    """Применить миграции сервиса к тестовой базе."""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            f"source/services/{service}/alembic.ini",
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
        pytest.fail(f"Миграции {service} не применились: {result.stdout}\n{result.stderr}")


def _service_env(service: str, database_url: str, rabbitmq_url: str) -> dict[str, str]:
    """Собрать окружение процесса uvicorn."""
    env = os.environ.copy()
    env.update(
        {
            "OTEL_ENABLED": "false",
            "ENVIRONMENT": "integration",
            "LOG_LEVEL": "ERROR",
            "SERVICE_NAME": service,
            "DATABASE_URL": database_url,
            "RABBITMQ_URL": rabbitmq_url,
            "CHECK_DEPENDENCIES": "true",
            "RUN_BACKGROUND_WORKERS": "true",
            "HEALTH_CHECK_TIMEOUT_SECONDS": "5",
            "AUDIT_CONSUMER_RECONNECT_SECONDS": "1",
        }
    )
    source_path = str(_REPO_ROOT / f"source/services/{service}/src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{source_path}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else source_path
    )
    return env


@contextmanager
def _run_service(
    module: str,
    env: dict[str, str],
    expected_checks: set[str],
) -> Iterator[str]:
    """Поднять uvicorn на свободном порту и вернуть базовый URL."""
    port = _free_port()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                module,
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
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        base_url = f"http://127.0.0.1:{port}"

        try:
            _wait_for_health(base_url, process, log_file, expected_checks)
            yield base_url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.fixture(scope="session")
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


@pytest.fixture(scope="module")
def audit_exporter_url(infrastructure: tuple[str, str]) -> Iterator[str]:
    """Поднять Audit Exporter и вернуть базовый URL."""
    database_url, rabbitmq_url = infrastructure
    _apply_migrations("audit_exporter", database_url)
    env = _service_env("audit_exporter", database_url, rabbitmq_url)
    with _run_service("audit_exporter.main:app", env, _AUDIT_EXPORTER_CHECKS) as base_url:
        yield base_url


@pytest.fixture(scope="module")
def notifications_url(infrastructure: tuple[str, str]) -> Iterator[str]:
    """Поднять Notifications и вернуть базовый URL."""
    database_url, rabbitmq_url = infrastructure
    _apply_migrations("notifications", database_url)
    env = _service_env("notifications", database_url, rabbitmq_url)
    with _run_service("notifications.main:app", env, _OUTBOX_CHECKS) as base_url:
        yield base_url


@pytest.fixture(scope="module")
def email_channel_url(infrastructure: tuple[str, str]) -> Iterator[str]:
    """Поднять Email Channel и вернуть базовый URL."""
    database_url, rabbitmq_url = infrastructure
    _apply_migrations("email_channel", database_url)
    env = _service_env("email_channel", database_url, rabbitmq_url)
    with _run_service("email_channel.main:app", env, _EMAIL_CHANNEL_CHECKS) as base_url:
        yield base_url
