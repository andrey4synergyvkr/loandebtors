"""Проверка сериализации сообщений RabbitMQ."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from notifications.adapters.messaging.serialization import encode_payload


class SampleStatus(StrEnum):
    """Тестовый статус для проверки сериализации."""

    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class SampleValue:
    """Тестовое значение для проверки сериализации dataclass."""

    name: str
    amount: Decimal


def test_encode_payload_serializes_domain_values() -> None:
    """UUID, время, Decimal, StrEnum и dataclass приводятся к JSON."""
    identifier = UUID("3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d")
    occurred_at = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)

    body = encode_payload(
        {
            "id": identifier,
            "occurred_at": occurred_at,
            "amount": Decimal("15000.00"),
            "status": SampleStatus.ACTIVE,
            "value": SampleValue(name="debtor", amount=Decimal("1.50")),
        }
    )

    payload = json.loads(body)
    assert payload["id"] == str(identifier)
    assert payload["occurred_at"] == occurred_at.isoformat()
    assert payload["amount"] == "15000.00"
    assert payload["status"] == "active"
    assert payload["value"] == {"name": "debtor", "amount": "1.50"}
