"""Декодирование тел сообщений RabbitMQ."""

import json
from collections.abc import Mapping

from audit_exporter.domain import ValidationError


def decode_payload(body: bytes) -> Mapping[str, object]:
    """Декодировать JSON-объект из тела сообщения."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Тело сообщения не является JSON") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Тело сообщения должно быть JSON-объектом")
    return payload
