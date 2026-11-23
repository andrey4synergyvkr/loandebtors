"""Интеграционная проверка приёма audit.event и выгрузки журнала."""

import asyncio
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import aio_pika
import asyncpg
import httpx
import pytest
from aio_pika import DeliveryMode

from audit_exporter.adapters.http.constants import AUDIT_RECORDS_PATH
from audit_exporter.adapters.messaging.constants import (
    AUDIT_QUEUE_NAME,
    EVENTS_EXCHANGE,
)

pytestmark = pytest.mark.integration

_REQUEST_TIMEOUT_SECONDS = 5.0
_POLL_TIMEOUT_SECONDS = 20.0


def _payload(
    *,
    event_id: UUID | None = None,
    campaign_id: UUID | None = None,
    action: str = "message.sent",
    channel: str = "email",
    service: str = "notifications",
    marker: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    current_event_id = event_id or uuid4()
    details: dict[str, str] = {"provider": "mailpit"}
    if marker is not None:
        details["marker"] = marker
    return {
        "event_id": str(current_event_id),
        "occurred_at": (occurred_at or datetime.now(UTC)).isoformat(),
        "service": service,
        "actor": {"type": "system", "identifier": service},
        "action": action,
        "entity_type": "message",
        "entity_id": str(current_event_id),
        "campaign_id": str(campaign_id or uuid4()),
        "message_id": str(current_event_id),
        "channel": channel,
        "outcome": "success",
        "details": details,
        "correlation_id": f"corr-{current_event_id}",
        "trace_id": None,
    }


async def _publish(
    rabbitmq_url: str,
    payload: Mapping[str, object],
    headers: Mapping[str, str] | None = None,
) -> None:
    """Опубликовать audit.event в exchange."""
    connection = await aio_pika.connect_robust(rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.get_exchange(EVENTS_EXCHANGE, ensure=True)
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
                headers=dict(headers or {}),
            ),
            routing_key="audit.event",
            mandatory=True,
        )


async def _publish_raw(rabbitmq_url: str, body: bytes) -> None:
    """Опубликовать исходное тело audit.event."""
    connection = await aio_pika.connect_robust(rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.get_exchange(EVENTS_EXCHANGE, ensure=True)
        await exchange.publish(
            aio_pika.Message(
                body=body,
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
            ),
            routing_key="audit.event",
            mandatory=True,
        )


async def _wait_for_record(base_url: str, event_id: UUID) -> dict[str, Any]:
    """Ждать появления записи в журнале и вернуть ее."""
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    async with httpx.AsyncClient(base_url=base_url, timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        while time.monotonic() < deadline:
            response = await client.get(AUDIT_RECORDS_PATH, params={"limit": 100})
            if response.status_code == 200:
                for item in response.json()["items"]:
                    if item["event"]["event_id"] == str(event_id):
                        return cast(dict[str, Any], item)
            await asyncio.sleep(0.2)
    pytest.fail(f"Запись {event_id} не появилась за {_POLL_TIMEOUT_SECONDS} секунд")


async def _wait_for_dlq(rabbitmq_url: str, marker: str) -> None:
    """Ждать сообщение с маркером в audit.events.dlq."""
    connection = await aio_pika.connect_robust(rabbitmq_url)
    try:
        channel = await connection.channel()
        queue = await channel.get_queue(f"{AUDIT_QUEUE_NAME}.dlq")
        deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            message = await queue.get(no_ack=True, fail=False)
            if message is not None and marker.encode("utf-8") in message.body:
                return
            await asyncio.sleep(0.2)
    finally:
        await connection.close()
    pytest.fail(f"Сообщение {marker} не появилось в DLQ за {_POLL_TIMEOUT_SECONDS} секунд")


async def test_ingest_and_get_by_event_id(
    audit_exporter_url: str,
    infrastructure: tuple[str, str],
) -> None:
    """Событие из RabbitMQ записывается и читается по event_id."""
    _, rabbitmq_url = infrastructure
    event_id = uuid4()
    await _publish(rabbitmq_url, _payload(event_id=event_id))

    item = await _wait_for_record(audit_exporter_url, event_id)

    assert item["event"]["service"] == "notifications"
    assert item["event"]["action"] == "message.sent"
    assert item["event"]["channel"] == "email"
    assert item["event"]["details"]["provider"] == "mailpit"
    async with httpx.AsyncClient(
        base_url=audit_exporter_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        response = await client.get(f"{AUDIT_RECORDS_PATH}/{event_id}")
    assert response.status_code == 200
    assert response.json()["event"]["event_id"] == str(event_id)


async def test_duplicate_event_is_stored_once(
    audit_exporter_url: str,
    infrastructure: tuple[str, str],
) -> None:
    """Повторная доставка не создаёт вторую запись."""
    _, rabbitmq_url = infrastructure
    event_id = uuid4()
    campaign_id = uuid4()
    payload = _payload(event_id=event_id, campaign_id=campaign_id)
    await asyncio.gather(
        _publish(rabbitmq_url, payload),
        _publish(rabbitmq_url, payload),
    )
    await _wait_for_record(audit_exporter_url, event_id)
    await asyncio.sleep(0.5)

    async with httpx.AsyncClient(
        base_url=audit_exporter_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        response = await client.get(
            AUDIT_RECORDS_PATH,
            params={
                "campaign_id": str(campaign_id),
                "action": "message.sent",
                "limit": 100,
            },
        )

    assert response.status_code == 200
    matching = [item for item in response.json()["items"] if item["event"]["event_id"] == str(event_id)]
    assert len(matching) == 1


async def test_filters_and_cursor(
    audit_exporter_url: str,
    infrastructure: tuple[str, str],
) -> None:
    """Фильтры и курсор выдают записи в порядке sequence."""
    _, rabbitmq_url = infrastructure
    campaign_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    await _publish(rabbitmq_url, _payload(event_id=first_id, campaign_id=campaign_id))
    await _wait_for_record(audit_exporter_url, first_id)
    await _publish(rabbitmq_url, _payload(event_id=second_id, campaign_id=campaign_id))
    await _wait_for_record(audit_exporter_url, second_id)

    params: dict[str, str | int] = {
        "campaign_id": str(campaign_id),
        "action": "message.sent",
        "channel": "email",
        "limit": 1,
    }
    async with httpx.AsyncClient(
        base_url=audit_exporter_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        first_page = await client.get(AUDIT_RECORDS_PATH, params=params)
        assert first_page.status_code == 200
        first_payload = first_page.json()
        assert len(first_payload["items"]) == 1
        assert first_payload["next_cursor"] is not None
        cursor = first_payload["next_cursor"]

        second_page = await client.get(
            AUDIT_RECORDS_PATH,
            params={**params, "cursor": cursor},
        )

    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert len(second_payload["items"]) == 1
    assert second_payload["items"][0]["event"]["event_id"] == str(second_id)


async def test_time_filter_boundaries(
    audit_exporter_url: str,
    infrastructure: tuple[str, str],
) -> None:
    """occurred_from включителен, occurred_to не включителен."""
    _, rabbitmq_url = infrastructure
    campaign_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    first_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    second_time = first_time + timedelta(seconds=10)
    await _publish(
        rabbitmq_url,
        _payload(event_id=first_id, campaign_id=campaign_id, occurred_at=first_time),
    )
    await _wait_for_record(audit_exporter_url, first_id)
    await _publish(
        rabbitmq_url,
        _payload(event_id=second_id, campaign_id=campaign_id, occurred_at=second_time),
    )
    await _wait_for_record(audit_exporter_url, second_id)

    params: dict[str, str | int] = {
        "campaign_id": str(campaign_id),
        "action": "message.sent",
        "limit": 100,
    }
    async with httpx.AsyncClient(
        base_url=audit_exporter_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        before_second = await client.get(
            AUDIT_RECORDS_PATH,
            params={
                **params,
                "occurred_from": first_time.isoformat(),
                "occurred_to": second_time.isoformat(),
            },
        )
        from_second = await client.get(
            AUDIT_RECORDS_PATH,
            params={**params, "occurred_from": second_time.isoformat()},
        )

    before_items = before_second.json()["items"]
    assert [item["event"]["event_id"] for item in before_items] == [str(first_id)]
    from_items = from_second.json()["items"]
    assert [item["event"]["event_id"] for item in from_items] == [str(second_id)]


async def test_export_records_audit_exported(
    audit_exporter_url: str,
    infrastructure: tuple[str, str],
) -> None:
    """Первая страница выгрузки создаёт audit.exported."""
    _, rabbitmq_url = infrastructure
    event_id = uuid4()
    await _publish(rabbitmq_url, _payload(event_id=event_id))
    await _wait_for_record(audit_exporter_url, event_id)

    async with httpx.AsyncClient(
        base_url=audit_exporter_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        await client.get(AUDIT_RECORDS_PATH, params={"limit": 1})
        response = await client.get(
            AUDIT_RECORDS_PATH,
            params={"action": "audit.exported", "limit": 100},
        )

    assert response.status_code == 200
    exports = [item for item in response.json()["items"] if item["event"]["service"] == "audit_exporter"]
    assert exports
    assert exports[0]["event"]["actor"]["type"] == "administrator"


async def test_problem_responses(
    audit_exporter_url: str,
    infrastructure: tuple[str, str],
) -> None:
    """404 и 422 отдаются как Problem."""
    _, _ = infrastructure
    async with httpx.AsyncClient(
        base_url=audit_exporter_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        not_found = await client.get(f"{AUDIT_RECORDS_PATH}/{uuid4()}")
        invalid = await client.get(AUDIT_RECORDS_PATH, params={"limit": 0})

    assert not_found.status_code == 404
    assert not_found.headers["content-type"].startswith("application/problem+json")
    assert not_found.json()["code"] == "not_found"
    assert invalid.status_code == 422
    assert invalid.headers["content-type"].startswith("application/problem+json")
    assert invalid.json()["code"] == "validation_error"


async def test_journal_rejects_update_delete_and_truncate(
    audit_exporter_url: str,
    infrastructure: tuple[str, str],
) -> None:
    """Trigger запрещает изменение, удаление и очистку журнала."""
    database_url, _ = infrastructure
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
    connection = await asyncpg.connect(dsn)
    try:
        for statement in (
            "UPDATE audit.audit_record SET outcome = 'failure'",
            "DELETE FROM audit.audit_record",
            "TRUNCATE audit.audit_record",
        ):
            with pytest.raises(asyncpg.PostgresError):
                await connection.execute(statement)
    finally:
        await connection.close()


async def test_invalid_event_goes_to_dlq(
    audit_exporter_url: str,
    infrastructure: tuple[str, str],
) -> None:
    """Ошибка валидации отправляет сообщение в audit.events.dlq."""
    _, rabbitmq_url = infrastructure
    marker = f"dlq-{uuid4()}"
    payload = _payload(marker=marker)
    payload["action"] = "unknown.action"
    await _publish_raw(rabbitmq_url, json.dumps(payload).encode("utf-8"))

    await _wait_for_dlq(rabbitmq_url, marker)


async def test_conflicting_event_id_goes_to_dlq(
    audit_exporter_url: str,
    infrastructure: tuple[str, str],
) -> None:
    """Событие с тем же event_id и другим содержимым уходит в DLQ."""
    _, rabbitmq_url = infrastructure
    event_id = uuid4()
    campaign_id = uuid4()
    original = _payload(event_id=event_id, campaign_id=campaign_id, marker="original")
    await _publish(rabbitmq_url, original)
    await _wait_for_record(audit_exporter_url, event_id)

    conflict = _payload(event_id=event_id, campaign_id=campaign_id, marker="conflict")
    conflict["details"]["provider"] = "other"
    await _publish(rabbitmq_url, conflict)
    await _wait_for_dlq(rabbitmq_url, "conflict")

    async with httpx.AsyncClient(
        base_url=audit_exporter_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        response = await client.get(f"{AUDIT_RECORDS_PATH}/{event_id}")

    assert response.status_code == 200
    assert response.json()["event"]["details"]["marker"] == "original"
    assert response.json()["event"]["details"]["provider"] == "mailpit"
