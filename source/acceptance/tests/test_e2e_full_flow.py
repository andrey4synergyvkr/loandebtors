"""Сквозной сценарий системы на полном Docker-стенде."""

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.e2e

NOTIFICATIONS_URL = os.environ.get("NOTIFICATIONS_URL", "http://localhost:8001")
SCHEDULER_URL = os.environ.get("SCHEDULER_URL", "http://localhost:8002")
EMAIL_CHANNEL_URL = os.environ.get("EMAIL_CHANNEL_URL", "http://localhost:8003")
AUDIT_EXPORTER_URL = os.environ.get("AUDIT_EXPORTER_URL", "http://localhost:8004")
ABS_URL = os.environ.get("ABS_URL", "http://localhost:9000")
MAILPIT_URL = os.environ.get("MAILPIT_URL", "http://localhost:8025")
RABBITMQ_MANAGEMENT_URL = os.environ.get(
    "RABBITMQ_MANAGEMENT_URL",
    "http://localhost:15672",
)
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "loandebtors")
RABBITMQ_PASSWORD = os.environ.get("RABBITMQ_PASSWORD", "loandebtors")
REQUEST_TIMEOUT_SECONDS = 10.0
WAIT_TIMEOUT_SECONDS = float(os.environ.get("E2E_TIMEOUT_SECONDS", "120"))
POLL_INTERVAL_SECONDS = 0.5
DLQ_NAMES = (
    "scheduler.commands.dlq",
    "email.commands.dlq",
    "notification.results.dlq",
    "notification.commands.dlq",
    "audit.events.dlq",
)
EXPECTED_ACTIONS = {
    "campaign.created",
    "campaign.started",
    "message.queued",
    "message.sent",
    "campaign.completed",
}


def _client() -> httpx.Client:
    """Создать HTTP-клиент для проверок стенда."""
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)


def _wait_until(description: str, predicate: Callable[[], Any]) -> Any:
    """Повторять проверку до дедлайна и вернуть результат."""
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    last_error = "условие не выполнено"
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
            last_error = "условие вернуло ложь"
        except (httpx.HTTPError, AssertionError, KeyError) as exc:
            last_error = str(exc)
        time.sleep(POLL_INTERVAL_SECONDS)
    pytest.fail(f"{description}: {last_error}")


def _get(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """Выполнить GET и вернуть JSON."""
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.json()


def _post(client: httpx.Client, url: str, payload: dict[str, Any]) -> httpx.Response:
    """Выполнить POST с JSON-телом."""
    response = client.post(url, json=payload)
    response.raise_for_status()
    return response


def _put(client: httpx.Client, url: str, payload: dict[str, Any]) -> httpx.Response:
    """Выполнить PUT с JSON-телом."""
    response = client.put(url, json=payload)
    response.raise_for_status()
    return response


def _patch(client: httpx.Client, url: str, payload: dict[str, Any]) -> httpx.Response:
    """Выполнить PATCH с JSON-телом."""
    response = client.patch(url, json=payload)
    response.raise_for_status()
    return response


def _health(client: httpx.Client, url: str) -> dict[str, Any]:
    """Проверить health сервиса и вернуть ответ."""
    payload = cast(dict[str, Any], _get(client, f"{url}/health"))
    assert payload["status"] == "ok", payload
    return payload


def _configure_email_channel(client: httpx.Client) -> None:
    """Настроить SMTP-адаптер на Mailpit."""
    _put(
        client,
        f"{EMAIL_CHANNEL_URL}/v1/config",
        {
            "host": "mailpit",
            "port": 1025,
            "username": "mailpit",
            "password_ref": "SMTP_PASSWORD",
            "from_address": "noreply@loandebtors.local",
            "from_name": "LoanDebtors E2E",
            "use_starttls": False,
            "timeout_seconds": 10,
            "rate_limit_per_second": 20,
            "enabled": True,
        },
    )


def _create_email_template(
    client: httpx.Client,
    key: str,
    run_id: str,
) -> None:
    """Создать email-вариант шаблона."""
    _put(
        client,
        f"{EMAIL_CHANNEL_URL}/v1/templates/{key}/versions/1",
        {
            "locale": "ru-RU",
            "subject_template": f"E2E {run_id} {{{{ debtor_name }}}}",
            "html_template": ("<p>Здравствуйте, {{ debtor_name }}. Сумма {{ amount }} {{ currency }}.</p>"),
            "plain_text_template": ("Здравствуйте, {{ debtor_name }}. Сумма {{ amount }} {{ currency }}."),
            "required_variables": ["debtor_name", "amount", "currency"],
        },
    )


def _create_logical_template(
    client: httpx.Client,
    key: str,
) -> None:
    """Создать и активировать логический шаблон Notifications."""
    _post(
        client,
        f"{NOTIFICATIONS_URL}/v1/templates",
        {
            "key": key,
            "version": 1,
            "description": "Сквозной сценарий E2E",
            "required_variables": ["debtor_name", "amount", "currency"],
        },
    )
    _patch(
        client,
        f"{NOTIFICATIONS_URL}/v1/templates/{key}/versions/1",
        {"status": "active"},
    )


def _create_campaign(client: httpx.Client, key: str, name: str) -> str:
    """Создать кампанию и вернуть ее идентификатор."""
    response = _post(
        client,
        f"{NOTIFICATIONS_URL}/v1/campaigns",
        {
            "name": name,
            "channel": "email",
            "template_key": key,
            "template_version": 1,
            "selection": {"criteria": {"min_days_overdue": "360"}},
        },
    )
    return cast(str, response.json()["id"])


def _campaign(client: httpx.Client, campaign_id: str) -> dict[str, Any]:
    """Вернуть кампанию по идентификатору."""
    return cast(
        dict[str, Any],
        _get(client, f"{NOTIFICATIONS_URL}/v1/campaigns/{campaign_id}"),
    )


def _messages(client: httpx.Client, campaign_id: str) -> dict[str, Any]:
    """Вернуть страницу сообщений кампании."""
    return cast(
        dict[str, Any],
        _get(
            client,
            f"{NOTIFICATIONS_URL}/v1/campaigns/{campaign_id}/messages",
            params={"limit": 100},
        ),
    )


def _wait_completed(client: httpx.Client, campaign_id: str) -> dict[str, Any]:
    """Дождаться завершения кампании."""

    def completed() -> dict[str, Any] | None:
        campaign = _campaign(client, campaign_id)
        return campaign if campaign["status"] == "completed" else None

    return cast(dict[str, Any], _wait_until("Кампания не завершилась", completed))


def _wait_status(
    client: httpx.Client,
    campaign_id: str,
    status: str,
) -> dict[str, Any]:
    """Дождаться перехода кампании в заданный статус."""

    def reached() -> dict[str, Any] | None:
        campaign = _campaign(client, campaign_id)
        return campaign if campaign["status"] == status else None

    return cast(
        dict[str, Any],
        _wait_until(f"Кампания не перешла в статус {status}", reached),
    )


def _wait_messages_sent(client: httpx.Client, campaign_id: str) -> list[dict[str, Any]]:
    """Дождаться перехода всех сообщений в sent."""

    def sent() -> list[dict[str, Any]] | None:
        items = cast(list[dict[str, Any]], _messages(client, campaign_id)["items"])
        return items if items and all(item["status"] == "sent" for item in items) else None

    return cast(list[dict[str, Any]], _wait_until("Сообщения не отправлены", sent))


def _wait_mailpit(client: httpx.Client, run_id: str) -> dict[str, Any]:
    """Дождаться письма с уникальной темой."""

    def letter() -> dict[str, Any] | None:
        payload = cast(
            dict[str, Any],
            _get(client, f"{MAILPIT_URL}/api/v1/messages"),
        )
        for item in payload.get("messages", []):
            if run_id in str(item.get("Subject", "")):
                return cast(dict[str, Any], item)
        return None

    return cast(dict[str, Any], _wait_until("Письмо не появилось в Mailpit", letter))


def _audit_records(client: httpx.Client, campaign_id: str) -> list[dict[str, Any]]:
    """Вернуть audit-записи кампании."""
    payload = cast(
        dict[str, Any],
        _get(
            client,
            f"{AUDIT_EXPORTER_URL}/v1/audit-records",
            params={"campaign_id": campaign_id, "limit": 200},
        ),
    )
    return cast(list[dict[str, Any]], payload["items"])


def _wait_audit_actions(
    client: httpx.Client,
    campaign_id: str,
    expected: set[str],
) -> set[str]:
    """Дождаться появления ожидаемых audit-действий."""

    def actions() -> set[str] | None:
        found = {str(item["event"]["action"]) for item in _audit_records(client, campaign_id)}
        return found if expected <= found else None

    return cast(set[str], _wait_until("В журнале нет ожидаемых действий", actions))


def _queue_depth(client: httpx.Client, queue_name: str) -> int:
    """Вернуть глубину очереди RabbitMQ."""
    response = client.get(
        f"{RABBITMQ_MANAGEMENT_URL}/api/queues/%2F/{quote(queue_name, safe='')}",
        auth=(RABBITMQ_USER, RABBITMQ_PASSWORD),
    )
    if response.status_code == 404:
        return 0
    response.raise_for_status()
    return int(response.json().get("messages", 0))


def _wait_dlq_empty(client: httpx.Client) -> None:
    """Дождаться пустых dead-letter очередей."""

    def empty() -> bool:
        return all(_queue_depth(client, name) == 0 for name in DLQ_NAMES)

    _wait_until("DLQ не пусты", empty)


def _preflight(client: httpx.Client) -> None:
    """Проверить здоровье всех сервисов стенда."""
    for url in (
        NOTIFICATIONS_URL,
        SCHEDULER_URL,
        EMAIL_CHANNEL_URL,
        AUDIT_EXPORTER_URL,
        ABS_URL,
    ):
        _health(client, url)
    response = client.get(f"{MAILPIT_URL}/api/v1/messages")
    response.raise_for_status()


def _run_immediate_campaign(client: httpx.Client, run_id: str) -> str:
    """Провести кампанию с немедленным запуском."""
    key = f"e2e-immediate-{run_id}"
    _create_email_template(client, key, run_id)
    _create_logical_template(client, key)
    campaign_id = _create_campaign(client, key, f"E2E immediate {run_id}")
    _post(client, f"{NOTIFICATIONS_URL}/v1/campaigns/{campaign_id}/start", {})
    return campaign_id


def _run_scheduled_campaign(client: httpx.Client, run_id: str) -> str:
    """Провести кампанию через Scheduler."""
    key = f"e2e-scheduled-{run_id}"
    _create_email_template(client, key, run_id)
    _create_logical_template(client, key)
    campaign_id = _create_campaign(client, key, f"E2E scheduled {run_id}")
    run_at = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=8)
    _post(
        client,
        f"{NOTIFICATIONS_URL}/v1/campaigns/{campaign_id}/schedule",
        {
            "schedule": {
                "kind": "one_off",
                "timezone": "UTC",
                "run_at": run_at.isoformat(),
                "cron": None,
            }
        },
    )
    return campaign_id


def test_immediate_campaign_is_delivered_and_audited() -> None:
    """Кампания проходит ABS, Email Channel, Mailpit и Audit Exporter."""
    run_id = uuid4().hex[:12]
    with _client() as client:
        _preflight(client)
        _configure_email_channel(client)
        campaign_id = _run_immediate_campaign(client, run_id)

        _wait_completed(client, campaign_id)
        messages = _wait_messages_sent(client, campaign_id)
        assert messages
        _wait_mailpit(client, run_id)
        actions = _wait_audit_actions(client, campaign_id, EXPECTED_ACTIONS)
        assert "campaign.completed" in actions
        _wait_dlq_empty(client)


def test_scheduled_campaign_is_triggered_by_scheduler() -> None:
    """Запланированная кампания запускается Scheduler и доходит до Mailpit."""
    run_id = uuid4().hex[:12]
    with _client() as client:
        _preflight(client)
        _configure_email_channel(client)
        campaign_id = _run_scheduled_campaign(client, run_id)

        campaign = _wait_completed(client, campaign_id)
        assert campaign["schedule"]["kind"] == "one_off"
        _wait_messages_sent(client, campaign_id)
        _wait_mailpit(client, run_id)
        actions = _wait_audit_actions(
            client,
            campaign_id,
            EXPECTED_ACTIONS | {"campaign.scheduled"},
        )
        assert "campaign.scheduled" in actions
        _wait_dlq_empty(client)


def test_scheduled_campaign_can_be_cancelled_before_run() -> None:
    """Отмена запланированной кампании снимает задание Scheduler."""
    run_id = uuid4().hex[:12]
    with _client() as client:
        _preflight(client)
        _configure_email_channel(client)
        key = f"e2e-cancel-{run_id}"
        _create_email_template(client, key, run_id)
        _create_logical_template(client, key)
        campaign_id = _create_campaign(client, key, f"E2E cancel {run_id}")
        run_at = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=8)
        _post(
            client,
            f"{NOTIFICATIONS_URL}/v1/campaigns/{campaign_id}/schedule",
            {
                "schedule": {
                    "kind": "one_off",
                    "timezone": "UTC",
                    "run_at": run_at.isoformat(),
                    "cron": None,
                }
            },
        )
        _post(
            client,
            f"{NOTIFICATIONS_URL}/v1/campaigns/{campaign_id}/cancel",
            {},
        )

        campaign = _wait_status(client, campaign_id, "cancelled")
        assert campaign["status"] == "cancelled"
        actions = _wait_audit_actions(
            client,
            campaign_id,
            {"campaign.scheduled", "campaign.cancelled"},
        )
        assert "campaign.cancelled" in actions

        time.sleep(max(0.0, (run_at - datetime.now(UTC)).total_seconds()) + 2.0)

        campaign = _campaign(client, campaign_id)
        assert campaign["status"] == "cancelled"
        actions = {str(item["event"]["action"]) for item in _audit_records(client, campaign_id)}
        assert "campaign.started" not in actions
        assert _messages(client, campaign_id)["items"] == []
        _wait_dlq_empty(client)
