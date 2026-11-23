"""Проверка топологии RabbitMQ против AsyncAPI."""

from pathlib import Path
from typing import Any

import yaml

from notifications.adapters.messaging.constants import QUEUE_DEFINITIONS

_REPO_ROOT = Path(__file__).resolve().parents[5]
_ASYNCAPI_PATH = _REPO_ROOT / "source/contracts/asyncapi/loandebtors.yaml"


def test_queue_definitions_match_asyncapi() -> None:
    """Очереди, routing keys, retry-очереди и DLQ совпадают с контрактом."""
    contract = yaml.safe_load(_ASYNCAPI_PATH.read_text(encoding="utf-8"))
    channels: dict[str, Any] = contract["channels"]

    expected: dict[str, tuple[tuple[str, ...], str, str]] = {}
    for channel in channels.values():
        address = channel["address"]
        routing_keys = tuple(channel["x-routing-keys"])
        expected[address] = (routing_keys, channel["x-retry-queue"], channel["x-dlq"])

    actual = {
        definition.name.value: (
            tuple(key.value for key in definition.routing_keys),
            definition.retry_name,
            definition.dlq_name,
        )
        for definition in QUEUE_DEFINITIONS
    }

    assert actual == expected
