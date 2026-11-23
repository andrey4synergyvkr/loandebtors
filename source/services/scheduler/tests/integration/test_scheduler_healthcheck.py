"""Интеграционная проверка запуска Scheduler с зависимостями."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import aio_pika
import httpx
import pytest
from aio_pika import Message
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from scheduler.adapters.http.constants import HEALTH_PATH
from scheduler.adapters.messaging.constants import EVENTS_EXCHANGE, QueueName, RoutingKey
from scheduler.application.health import (
    APPLICATION_CHECK_NAME,
    CONSUMER_CHECK_NAME,
    DATABASE_CHECK_NAME,
    OUTBOX_RELAY_CHECK_NAME,
    RABBITMQ_CHECK_NAME,
    SCHEDULER_CHECK_NAME,
)

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[5]
_STARTUP_TIMEOUT_SECONDS = 90.0
_REQUEST_TIMEOUT_SECONDS = 5.0
_MESSAGE_TIMEOUT_SECONDS = 20.0
_NEGATIVE_TIMEOUT_SECONDS = 2.0
_RABBITMQ_LOG_TIMEOUT_SECONDS = 60
_POSTGRES_IMAGE = "postgres:16-alpine"
_RABBITMQ_IMAGE = "rabbitmq:3.13-alpine"


@dataclass(frozen=True, slots=True)
class SchedulerRuntime:
    """Адреса запущенного сервиса и его брокера.

    Attributes:
        base_url: HTTP-адрес сервиса.
        rabbitmq_url: AMQP DSN тестового RabbitMQ.
    """

    base_url: str
    rabbitmq_url: str


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
                    SCHEDULER_CHECK_NAME,
                    CONSUMER_CHECK_NAME,
                    OUTBOX_RELAY_CHECK_NAME,
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
    """Применить миграции Scheduler к тестовой базе."""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "source/services/scheduler/alembic.ini",
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
def scheduler_runtime(infrastructure: tuple[str, str]) -> Iterator[SchedulerRuntime]:
    """Поднять uvicorn на свободном порту и вернуть адреса сервиса."""
    database_url, rabbitmq_url = infrastructure
    _apply_migrations(database_url)

    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "OTEL_ENABLED": "false",
            "ENVIRONMENT": "integration",
            "SERVICE_NAME": "scheduler",
            "DATABASE_URL": database_url,
            "RABBITMQ_URL": rabbitmq_url,
            "CHECK_DEPENDENCIES": "true",
            "RUN_BACKGROUND_WORKERS": "true",
            "HEALTH_CHECK_TIMEOUT_SECONDS": "5",
            "OUTBOX_POLL_INTERVAL_SECONDS": "0.2",
        }
    )
    source_path = str(_REPO_ROOT / "source/services/scheduler/src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{source_path}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else source_path
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "scheduler.main:app",
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
        yield SchedulerRuntime(base_url=base_url, rabbitmq_url=rabbitmq_url)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_service_starts_with_dependencies_and_returns_health(
    scheduler_runtime: SchedulerRuntime,
) -> None:
    """Сервис поднимается с зависимостями и отдаёт полный health."""
    response = httpx.get(
        f"{scheduler_runtime.base_url}{HEALTH_PATH}",
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "scheduler"
    assert payload["version"]
    assert payload["uptime_seconds"] >= 0
    checks = {check["name"]: check["status"] for check in payload["checks"]}
    assert checks[APPLICATION_CHECK_NAME] == "ok"
    assert checks[DATABASE_CHECK_NAME] == "ok"
    assert checks[RABBITMQ_CHECK_NAME] == "ok"
    assert checks[SCHEDULER_CHECK_NAME] == "ok"
    assert checks[CONSUMER_CHECK_NAME] == "ok"
    assert checks[OUTBOX_RELAY_CHECK_NAME] == "ok"


async def _publish(
    runtime: SchedulerRuntime,
    routing_key: str,
    payload: dict[str, object],
    correlation_id: str,
) -> None:
    """Опубликовать команду в exchange планировщика."""
    connection = await aio_pika.connect_robust(runtime.rabbitmq_url)
    try:
        channel = await connection.channel()
        exchange = await channel.get_exchange(EVENTS_EXCHANGE, ensure=True)
        await exchange.publish(
            Message(
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                content_type="application/json",
                headers={"correlation_id": correlation_id},
            ),
            routing_key=routing_key,
        )
    finally:
        await connection.close()


async def _get_message(
    runtime: SchedulerRuntime,
    queue_name: str,
    wait_seconds: float = _MESSAGE_TIMEOUT_SECONDS,
) -> dict[str, object] | None:
    """Забрать одно сообщение очереди, ожидая его появления."""
    connection = await aio_pika.connect_robust(runtime.rabbitmq_url)
    try:
        channel = await connection.channel()
        queue = await channel.get_queue(queue_name, ensure=True)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while loop.time() < deadline:
            message = await queue.get(no_ack=True, fail=False, timeout=1)
            if message is not None:
                return cast(dict[str, object], json.loads(message.body))
            await asyncio.sleep(0.2)
        return None
    finally:
        await connection.close()


async def test_scheduler_processes_schedule_and_cancel(scheduler_runtime: SchedulerRuntime) -> None:
    """Сервис принимает расписание, публикует запуск и снимает задание."""
    scheduled_campaign = str(uuid4())
    run_at = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=2)
    await _publish(
        scheduler_runtime,
        RoutingKey.CAMPAIGN_SCHEDULED.value,
        {
            "campaign_id": scheduled_campaign,
            "schedule": {
                "kind": "one_off",
                "timezone": "Europe/Moscow",
                "run_at": run_at.isoformat(),
                "cron": None,
            },
            "occurred_at": datetime.now(UTC).isoformat(),
        },
        "corr-schedule",
    )

    scheduled_audit = await _get_message(
        scheduler_runtime,
        QueueName.AUDIT_EVENTS.value,
    )
    assert scheduled_audit is not None
    assert scheduled_audit["action"] == "campaign.scheduled"
    assert scheduled_audit["campaign_id"] == scheduled_campaign

    start = await _get_message(
        scheduler_runtime,
        QueueName.NOTIFICATION_COMMANDS.value,
    )
    assert start is not None
    assert start["campaign_id"] == scheduled_campaign
    assert datetime.fromisoformat(str(start["scheduled_for"])) == run_at

    started_audit = await _get_message(
        scheduler_runtime,
        QueueName.AUDIT_EVENTS.value,
    )
    assert started_audit is not None
    assert started_audit["action"] == "campaign.started"

    cancelled_campaign = str(uuid4())
    future_run = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)
    await _publish(
        scheduler_runtime,
        RoutingKey.CAMPAIGN_SCHEDULED.value,
        {
            "campaign_id": cancelled_campaign,
            "schedule": {
                "kind": "one_off",
                "timezone": "Europe/Moscow",
                "run_at": future_run.isoformat(),
                "cron": None,
            },
            "occurred_at": datetime.now(UTC).isoformat(),
        },
        "corr-cancel",
    )
    future_audit = await _get_message(
        scheduler_runtime,
        QueueName.AUDIT_EVENTS.value,
    )
    assert future_audit is not None
    assert future_audit["action"] == "campaign.scheduled"
    assert future_audit["campaign_id"] == cancelled_campaign

    await _publish(
        scheduler_runtime,
        RoutingKey.CAMPAIGN_CANCELLED.value,
        {
            "campaign_id": cancelled_campaign,
            "occurred_at": datetime.now(UTC).isoformat(),
        },
        "corr-cancel",
    )
    cancelled_audit = await _get_message(
        scheduler_runtime,
        QueueName.AUDIT_EVENTS.value,
    )
    assert cancelled_audit is not None
    assert cancelled_audit["action"] == "campaign.cancelled"
    assert cancelled_audit["campaign_id"] == cancelled_campaign

    leftover = await _get_message(
        scheduler_runtime,
        QueueName.NOTIFICATION_COMMANDS.value,
        wait_seconds=_NEGATIVE_TIMEOUT_SECONDS,
    )
    assert leftover is None
