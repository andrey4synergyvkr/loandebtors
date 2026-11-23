"""Интеграционная проверка отправки message.send в Email Channel."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, cast
from uuid import uuid4

import aio_pika
import httpx
import pytest
from aio_pika import DeliveryMode
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[5]
_POSTGRES_IMAGE = "postgres:16-alpine"
_RABBITMQ_IMAGE = "rabbitmq:3.13-alpine"
_MAILPIT_IMAGE = "axllent/mailpit:latest"
_STARTUP_TIMEOUT_SECONDS = 90.0
_POLL_TIMEOUT_SECONDS = 20.0
_REQUEST_TIMEOUT_SECONDS = 5.0
_HEALTH_CHECKS = {"application", "database", "rabbitmq", "outbox_relay", "email_consumer"}


@dataclass(frozen=True)
class Stack:
    """Адреса тестовых контейнеров."""

    database_url: str
    rabbitmq_url: str
    smtp_host: str
    smtp_port: int
    mailpit_api: str


def _free_port() -> int:
    """Найти свободный TCP-порт."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_health(
    base_url: str,
    process: subprocess.Popen[str],
    log_file: IO[str],
    timeout: float = _STARTUP_TIMEOUT_SECONDS,
) -> None:
    """Ждать полной готовности Email Channel."""
    deadline = time.monotonic() + timeout
    last_error = "нет ответа"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_file.flush()
            log_file.seek(0)
            pytest.fail(f"Email Channel завершился до healthcheck: {log_file.read()}")
        try:
            response = httpx.get(f"{base_url}/health", timeout=_REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 200:
                checks = {check["name"]: check["status"] for check in response.json()["checks"]}
                if _HEALTH_CHECKS.issubset(checks) and all(value == "ok" for value in checks.values()):
                    return
                last_error = f"не все проверки готовы: {checks}"
            else:
                last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.3)
    pytest.fail(f"Healthcheck Email Channel не прошел: {last_error}")


def _apply_migrations(database_url: str) -> None:
    """Применить миграции Email Channel."""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "source/services/email_channel/alembic.ini",
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
        pytest.fail(f"Миграции Email Channel не применились: {result.stdout}\n{result.stderr}")


def _wait_mailpit(api_url: str) -> None:
    """Ждать HTTP API Mailpit."""
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{api_url}/api/v1/messages", timeout=2.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    pytest.fail("Mailpit API не стал доступен")


@pytest.fixture(scope="module")
def stack() -> Iterator[Stack]:
    """Поднять PostgreSQL, RabbitMQ и Mailpit."""
    postgres: PostgresContainer | None = None
    rabbitmq: DockerContainer | None = None
    mailpit: DockerContainer | None = None
    try:
        postgres = PostgresContainer(_POSTGRES_IMAGE)
        rabbitmq = (
            DockerContainer(_RABBITMQ_IMAGE)
            .with_env("RABBITMQ_DEFAULT_USER", "loandebtors")
            .with_env("RABBITMQ_DEFAULT_PASS", "loandebtors")
            .with_exposed_ports(5672)
        )
        mailpit = DockerContainer(_MAILPIT_IMAGE).with_exposed_ports(1025, 8025)
        postgres.start()
        rabbitmq.waiting_for(
            LogMessageWaitStrategy("Server startup complete").with_startup_timeout(60)
        ).start()
        mailpit.start()
    except Exception as exc:
        for container in (mailpit, rabbitmq, postgres):
            with suppress(Exception):
                if container is not None:
                    container.stop()
        pytest.skip(f"Docker или тестовые контейнеры недоступны: {exc}")

    assert postgres is not None
    assert rabbitmq is not None
    assert mailpit is not None
    database_url = postgres.get_connection_url().replace(
        "postgresql+psycopg2",
        "postgresql+asyncpg",
    )
    rabbitmq_url = (
        "amqp://loandebtors:loandebtors@"
        f"{rabbitmq.get_container_host_ip()}:{rabbitmq.get_exposed_port(5672)}/"
    )
    smtp_host = mailpit.get_container_host_ip()
    smtp_port = mailpit.get_exposed_port(1025)
    mailpit_api = f"http://{smtp_host}:{mailpit.get_exposed_port(8025)}"
    _wait_mailpit(mailpit_api)
    _apply_migrations(database_url)

    try:
        yield Stack(
            database_url=database_url,
            rabbitmq_url=rabbitmq_url,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            mailpit_api=mailpit_api,
        )
    finally:
        for container in (mailpit, rabbitmq, postgres):
            with suppress(Exception):
                container.stop()


@pytest.fixture(scope="module")
def email_channel_url(stack: Stack) -> Iterator[str]:
    """Поднять Email Channel на свободном порту."""
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "OTEL_ENABLED": "false",
            "ENVIRONMENT": "integration",
            "LOG_LEVEL": "ERROR",
            "SERVICE_NAME": "email_channel",
            "DATABASE_URL": stack.database_url,
            "RABBITMQ_URL": stack.rabbitmq_url,
            "SMTP_HOST": stack.smtp_host,
            "SMTP_PORT": str(stack.smtp_port),
            "SMTP_PASSWORD": "",
            "EMAIL_DEFAULT_LOCALE": "ru-RU",
            "CHECK_DEPENDENCIES": "true",
            "RUN_BACKGROUND_WORKERS": "true",
            "HEALTH_CHECK_TIMEOUT_SECONDS": "5",
            "EMAIL_CONSUMER_RECONNECT_SECONDS": "1",
        }
    )
    source_path = str(_REPO_ROOT / "source/services/email_channel/src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{source_path}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else source_path
    )
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "email_channel.main:app",
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
            _wait_health(base_url, process, log_file)
            yield base_url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


async def _configure_channel(base_url: str, stack: Stack) -> None:
    """Сохранить настройки и email-шаблон."""
    async with httpx.AsyncClient(base_url=base_url, timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        config = await client.put(
            "/v1/config",
            json={
                "host": stack.smtp_host,
                "port": stack.smtp_port,
                "username": "user",
                "password_ref": "SMTP_PASSWORD",
                "from_address": "noreply@example.com",
                "from_name": "Bank",
                "use_starttls": False,
                "timeout_seconds": 5,
                "rate_limit_per_second": 100,
                "enabled": True,
            },
        )
        template = await client.put(
            "/v1/templates/payment-reminder/versions/1",
            json={
                "locale": "ru-RU",
                "subject_template": "Напоминание {{ name }}",
                "html_template": "<p>Здравствуйте, {{ name }}</p>",
                "plain_text_template": "Здравствуйте, {{ name }}",
                "required_variables": ["name"],
            },
        )
    assert config.status_code == 200, config.text
    assert template.status_code == 200, template.text


async def _publish(rabbitmq_url: str, payload: dict[str, object]) -> None:
    """Опубликовать message.send в email.commands."""
    connection = await aio_pika.connect_robust(rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.get_exchange("loan-debtors.events", ensure=True)
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
                headers={"correlation_id": "corr-1"},
            ),
            routing_key="message.send",
            mandatory=True,
        )


async def _wait_for_queue_message(
    rabbitmq_url: str,
    queue_name: str,
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    """Ждать сообщение в очереди, удовлетворяющее предикату.

    Посторонние сообщения подтверждаются: иначе requeue возвращает их в голову
    очереди и ожидание зацикливается на уже просмотренных событиях.
    """
    connection = await aio_pika.connect_robust(rabbitmq_url)
    try:
        channel = await connection.channel()
        queue = await channel.get_queue(queue_name)
        deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            message = await queue.get(no_ack=False, fail=False)
            if message is None:
                await asyncio.sleep(0.2)
                continue
            payload = json.loads(message.body)
            if predicate(payload):
                await message.ack()
                return cast(dict[str, Any], payload)
            await message.ack()
            await asyncio.sleep(0.05)
    finally:
        await connection.close()
    pytest.fail(f"Сообщение в {queue_name} не найдено за {_POLL_TIMEOUT_SECONDS} секунд")


def _command(message_id: str, template_key: str = "payment-reminder") -> dict[str, object]:
    campaign_id = str(uuid4())
    return {
        "message_id": message_id,
        "campaign_id": campaign_id,
        "debtor_id": "ABS-100500",
        "channel": "email",
        "template_key": template_key,
        "template_version": 1,
        "variables": {"name": "Иван"},
        "recipient": {"channel": "email", "address": "debtor@example.com"},
        "idempotency_key": f"{campaign_id}:ABS-100500:email",
    }


async def test_message_send_is_delivered_and_audited(
    email_channel_url: str,
    stack: Stack,
) -> None:
    """message.send отправляет письмо, публикует результат и audit."""
    await _configure_channel(email_channel_url, stack)
    message_id = str(uuid4())
    await _publish(stack.rabbitmq_url, _command(message_id))

    result = await _wait_for_queue_message(
        stack.rabbitmq_url,
        "notification.results",
        lambda item: item.get("message_id") == message_id,
    )
    assert result["attempt_number"] == 1

    audit = await _wait_for_queue_message(
        stack.rabbitmq_url,
        "audit.events",
        lambda item: item.get("message_id") == message_id,
    )
    assert audit["action"] == "message.sent"
    assert audit["service"] == "email_channel"

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        messages = await client.get(f"{stack.mailpit_api}/api/v1/messages")
    assert messages.status_code == 200
    subjects = [item.get("Subject", "") for item in messages.json().get("messages", [])]
    assert any("Напоминание Иван" in subject for subject in subjects)


async def test_missing_template_publishes_failed_result(
    email_channel_url: str,
    stack: Stack,
) -> None:
    """Отсутствующий шаблон даёт message.failed и audit message.failed."""
    await _configure_channel(email_channel_url, stack)
    message_id = str(uuid4())
    await _publish(stack.rabbitmq_url, _command(message_id, template_key="missing"))

    result = await _wait_for_queue_message(
        stack.rabbitmq_url,
        "notification.results",
        lambda item: item.get("message_id") == message_id,
    )
    assert result["outcome"] == "permanent_failure"
    assert result["retryable"] is False
    assert result["error_code"] == "template_not_found"

    audit = await _wait_for_queue_message(
        stack.rabbitmq_url,
        "audit.events",
        lambda item: item.get("message_id") == message_id,
    )
    assert audit["action"] == "message.failed"
