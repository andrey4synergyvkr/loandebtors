"""Проверка разбора команд Scheduler и политики повторов."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from scheduler.adapters.messaging.commands import (
    decode_for_dead_letter,
    parse_command,
    retry_attempts,
    should_dead_letter,
)
from scheduler.domain import CampaignCancelled, CampaignScheduled, ScheduleKind, ValidationError

CAMPAIGN_ID = "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"


def _scheduled_body(**overrides: object) -> bytes:
    """Собрать тело campaign.scheduled."""
    payload: dict[str, object] = {
        "campaign_id": CAMPAIGN_ID,
        "schedule": {
            "kind": "one_off",
            "timezone": "Europe/Moscow",
            "run_at": "2026-12-01T10:00:00Z",
            "cron": None,
        },
        "occurred_at": "2026-11-22T12:00:00Z",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def test_parse_campaign_scheduled() -> None:
    """Событие campaign.scheduled преобразуется в доменную команду."""
    command = parse_command("campaign.scheduled", _scheduled_body())

    assert isinstance(command, CampaignScheduled)
    assert command.campaign_id == UUID(CAMPAIGN_ID)
    assert command.schedule.kind is ScheduleKind.ONE_OFF
    assert command.occurred_at == datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def test_parse_campaign_cancelled() -> None:
    """Событие campaign.cancelled преобразуется в доменную команду."""
    body = json.dumps(
        {
            "campaign_id": CAMPAIGN_ID,
            "occurred_at": "2026-11-22T12:30:00Z",
        }
    ).encode("utf-8")

    command = parse_command("campaign.cancelled", body)

    assert isinstance(command, CampaignCancelled)
    assert command.campaign_id == UUID(CAMPAIGN_ID)


def test_parse_retry_queue_scheduled_by_schedule_field() -> None:
    """После retry campaign.scheduled распознается по полю schedule."""
    command = parse_command("scheduler.commands", _scheduled_body())

    assert isinstance(command, CampaignScheduled)
    assert command.campaign_id == UUID(CAMPAIGN_ID)


def test_parse_retry_queue_cancelled_without_schedule_field() -> None:
    """После retry campaign.cancelled распознается по отсутствию schedule."""
    body = json.dumps(
        {
            "campaign_id": CAMPAIGN_ID,
            "occurred_at": "2026-11-22T12:30:00Z",
        }
    ).encode("utf-8")

    command = parse_command("scheduler.commands", body)

    assert isinstance(command, CampaignCancelled)
    assert command.campaign_id == UUID(CAMPAIGN_ID)


def test_parse_retry_queue_rejects_invalid_json() -> None:
    """Мусор из retry-очереди не превращается в событие."""
    with pytest.raises(ValidationError):
        parse_command("scheduler.commands", b"{not-json")


@pytest.mark.parametrize(
    ("routing_key", "body"),
    [
        ("message.send", _scheduled_body()),
        ("campaign.scheduled", b"{not-json"),
        ("campaign.scheduled", _scheduled_body(extra="value")),
        ("campaign.scheduled", _scheduled_body(occurred_at="2026-11-22T12:00:00")),
        (
            "campaign.scheduled",
            _scheduled_body(
                schedule={
                    "kind": "one_off",
                    "timezone": "Europe/Moscow",
                    "run_at": None,
                    "cron": None,
                }
            ),
        ),
        ("campaign.cancelled", b"{}"),
    ],
)
def test_invalid_command_is_rejected(routing_key: str, body: bytes) -> None:
    """Некорректные сообщения отклоняются доменной ошибкой."""
    with pytest.raises(ValidationError):
        parse_command(routing_key, body)


def test_retry_attempts_reads_x_death() -> None:
    """Счетчик повторов берется из dead-letter заголовка retry-очереди."""
    headers = {
        "x-death": [
            {"queue": "scheduler.commands.retry", "count": 2},
            {"queue": "audit.events.retry", "count": 5},
        ]
    }

    assert retry_attempts(headers) == 2
    assert should_dead_letter(headers, max_attempts=2) is True
    assert should_dead_letter(headers, max_attempts=3) is False


def test_retry_attempts_ignores_missing_header() -> None:
    """Без x-death повтор считается первым."""
    assert retry_attempts({}) == 0
    assert should_dead_letter({}, max_attempts=1) is False


def test_decode_for_dead_letter_keeps_json_and_raw_body() -> None:
    """DLQ получает исходный JSON или текстовое представление."""
    assert decode_for_dead_letter(b'{"campaign_id":"1"}') == {"campaign_id": "1"}
    assert decode_for_dead_letter(b"\xff") == {"raw": "\ufffd"}
