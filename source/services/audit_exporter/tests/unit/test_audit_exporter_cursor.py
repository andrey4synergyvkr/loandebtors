"""Проверка кодирования и декодирования курсора."""

import base64
import json

import pytest

from audit_exporter.adapters.persistence.cursor import decode_cursor, encode_cursor
from audit_exporter.domain import ValidationError


def _encode(payload: object) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_cursor_roundtrip() -> None:
    """Курсор кодируется и декодируется без потерь."""
    cursor = encode_cursor(42)

    assert decode_cursor(cursor) == 42


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!",
        "",
        _encode({}),
        _encode({"v": 2, "sequence": 1}),
        _encode({"v": 1, "sequence": 0}),
        _encode({"v": 1, "sequence": "1"}),
        _encode({"v": 1, "sequence": True}),
        _encode([1, 2]),
    ],
)
def test_invalid_cursor_raises_validation_error(cursor: str) -> None:
    """Некорректный курсор даёт ValidationError."""
    with pytest.raises(ValidationError):
        decode_cursor(cursor)
