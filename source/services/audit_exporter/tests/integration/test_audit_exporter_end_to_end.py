"""Сквозные проверки producers -> RabbitMQ -> Audit Exporter."""

import asyncio
import time
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from audit_exporter.adapters.http.constants import AUDIT_RECORDS_PATH

pytestmark = pytest.mark.integration

_REQUEST_TIMEOUT_SECONDS = 5.0
_POLL_TIMEOUT_SECONDS = 25.0


async def _wait_for_audit_record(
    audit_exporter_url: str,
    params: dict[str, str | int],
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    """Ждать запись журнала, удовлетворяющую предикату."""
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    async with httpx.AsyncClient(
        base_url=audit_exporter_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        while time.monotonic() < deadline:
            response = await client.get(AUDIT_RECORDS_PATH, params=params)
            if response.status_code == 200:
                for item in response.json()["items"]:
                    if predicate(item):
                        return cast(dict[str, Any], item)
            await asyncio.sleep(0.2)
    pytest.fail(f"Запись журнала не появилась за {_POLL_TIMEOUT_SECONDS} секунд: {params}")


async def test_notifications_template_audit_reaches_exporter(
    audit_exporter_url: str,
    notifications_url: str,
) -> None:
    """Создание шаблона в Notifications попадает в журнал Audit Exporter."""
    template_key = f"audit-e2e-{uuid4().hex[:8]}"
    async with httpx.AsyncClient(
        base_url=notifications_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        response = await client.post(
            "/v1/templates",
            json={
                "key": template_key,
                "version": 1,
                "description": "Сквозная проверка аудита",
                "required_variables": [],
            },
        )

    assert response.status_code == 201, response.text
    record = await _wait_for_audit_record(
        audit_exporter_url,
        {"action": "template.created", "limit": 100},
        lambda item: item["event"]["entity_id"].startswith(f"{template_key}:"),
    )

    assert record["event"]["service"] == "notifications"
    assert record["event"]["action"] == "template.created"
    assert record["event"]["entity_type"] == "template"
    assert record["event"]["outcome"] == "success"
    assert record["event"]["details"]["key"] == template_key


async def test_email_channel_config_audit_reaches_exporter(
    audit_exporter_url: str,
    email_channel_url: str,
) -> None:
    """Настройка SMTP-адаптера публикует channel.config.updated."""
    async with httpx.AsyncClient(
        base_url=email_channel_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        response = await client.put(
            "/v1/config",
            json={
                "host": "smtp.example.com",
                "port": 587,
                "username": "user",
                "password_ref": "SMTP_PASSWORD",
                "from_address": "noreply@example.com",
                "from_name": "Bank",
                "use_starttls": True,
                "timeout_seconds": 30,
                "rate_limit_per_second": 10,
                "enabled": True,
            },
        )
        config_response = await client.get("/v1/config")

    assert response.status_code == 200, response.text
    assert config_response.status_code == 200
    record = await _wait_for_audit_record(
        audit_exporter_url,
        {"action": "channel.config.updated", "limit": 100},
        lambda item: item["event"]["service"] == "email_channel",
    )

    assert record["event"]["action"] == "channel.config.updated"
    assert record["event"]["entity_type"] == "channel"
    assert record["event"]["entity_id"] == "smtp"
    assert record["event"]["channel"] == "email"
    assert record["event"]["outcome"] == "success"
    assert record["event"]["details"]["host"] == "smtp.example.com"
    assert record["event"]["details"]["port"] == "587"
