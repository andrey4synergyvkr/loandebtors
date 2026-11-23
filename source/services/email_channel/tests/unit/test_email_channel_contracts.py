"""Смоук-тесты контрактов Email Channel."""

from pathlib import Path
from typing import Any, cast

import yaml

from email_channel.adapters.http.constants import (
    CONFIG_PATH,
    CONFIG_VALIDATE_PATH,
    HEALTH_PATH,
    TEMPLATE_VERSION_PATH,
    TEMPLATES_PATH,
)
from email_channel.adapters.messaging.constants import QUEUE_DEFINITIONS
from email_channel.domain import AuditAction, AuditActorType, AuditOutcome

_REPO_ROOT = Path(__file__).resolve().parents[5]
_OPENAPI_PATH = _REPO_ROOT / "source/contracts/openapi/email-channel.yaml"
_ASYNCAPI_PATH = _REPO_ROOT / "source/contracts/asyncapi/loandebtors.yaml"


def _openapi() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(_OPENAPI_PATH.read_text(encoding="utf-8")))


def _asyncapi() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(_ASYNCAPI_PATH.read_text(encoding="utf-8")))


def test_api_paths_match_contract() -> None:
    """HTTP-константы совпадают с путями OpenAPI."""
    contract = _openapi()

    assert HEALTH_PATH in contract["paths"]
    assert CONFIG_PATH in contract["paths"]
    assert CONFIG_VALIDATE_PATH in contract["paths"]
    assert TEMPLATES_PATH in contract["paths"]
    assert TEMPLATE_VERSION_PATH in contract["paths"]


def test_operation_ids_match_contract() -> None:
    """OperationId совпадают с контрактом."""
    contract = _openapi()

    assert contract["paths"][HEALTH_PATH]["get"]["operationId"] == "getHealth"
    assert contract["paths"][CONFIG_PATH]["get"]["operationId"] == "getChannelConfig"
    assert contract["paths"][CONFIG_PATH]["put"]["operationId"] == "updateChannelConfig"
    assert contract["paths"][CONFIG_VALIDATE_PATH]["post"]["operationId"] == "validateChannelConfig"
    assert contract["paths"][TEMPLATES_PATH]["get"]["operationId"] == "listEmailTemplates"
    assert contract["paths"][TEMPLATE_VERSION_PATH]["get"]["operationId"] == "getEmailTemplate"
    assert contract["paths"][TEMPLATE_VERSION_PATH]["put"]["operationId"] == "upsertEmailTemplate"


def test_audit_action_values_match_contract() -> None:
    """Словарь audit-действий совпадает с AsyncAPI."""
    schemas = _asyncapi()["components"]["schemas"]

    assert {action.value for action in AuditAction} == set(schemas["AuditAction"]["enum"])


def test_audit_enums_match_contract() -> None:
    """Типы актора и результата совпадают с AsyncAPI."""
    schemas = _asyncapi()["components"]["schemas"]

    assert {value.value for value in AuditActorType} == set(schemas["AuditActorType"]["enum"])
    assert {value.value for value in AuditOutcome} == set(schemas["AuditOutcome"]["enum"])


def test_queue_definitions_match_asyncapi() -> None:
    """Очереди, routing keys, retry-очереди и DLQ совпадают с контрактом."""
    channels = _asyncapi()["channels"]

    expected: dict[str, tuple[tuple[str, ...], str, str]] = {}
    for channel in channels.values():
        expected[channel["address"]] = (
            tuple(channel["x-routing-keys"]),
            channel["x-retry-queue"],
            channel["x-dlq"],
        )

    actual = {
        definition.name.value: (
            tuple(key.value for key in definition.routing_keys),
            definition.retry_name,
            definition.dlq_name,
        )
        for definition in QUEUE_DEFINITIONS
    }

    assert actual == expected


def test_health_schema_is_full() -> None:
    """Health отдаёт статус, версию, uptime и проверки."""
    schema = _openapi()["components"]["schemas"]["HealthResponse"]

    assert set(schema["required"]) == {
        "status",
        "service",
        "version",
        "uptime_seconds",
        "checks",
    }
