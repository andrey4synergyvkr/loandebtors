"""Непрозрачный курсор постраничного чтения журнала."""

import base64
import binascii
import json
from typing import Final

from audit_exporter.domain import ValidationError

CURSOR_VERSION: Final = 1


def encode_cursor(sequence: int) -> str:
    """Закодировать sequence последней записи страницы в base64url."""
    payload = json.dumps(
        {"v": CURSOR_VERSION, "sequence": sequence},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> int:
    """Декодировать курсор и вернуть sequence, после которого читать журнал."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError("Некорректный курсор") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Некорректный курсор")
    if payload.get("v") != CURSOR_VERSION:
        raise ValidationError("Неподдерживаемая версия курсора")
    sequence = payload.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise ValidationError("Некорректный курсор")
    return sequence
