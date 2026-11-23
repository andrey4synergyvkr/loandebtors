"""Сериализация тел сообщений RabbitMQ."""

import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID


def encode_payload(payload: Mapping[str, object]) -> bytes:
    """Сериализовать JSON-совместимый payload в байты UTF-8."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    """Преобразовать доменное значение в JSON-совместимое."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"Неподдерживаемый тип для JSON: {type(value).__name__}")
