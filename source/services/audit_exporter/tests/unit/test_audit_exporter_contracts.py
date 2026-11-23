"""Смоук-тесты контрактов домена и API Audit Exporter."""

from dataclasses import fields
from pathlib import Path
from typing import Any, cast

import yaml

from audit_exporter.adapters.http.constants import (
    AUDIT_RECORD_PATH,
    AUDIT_RECORDS_PATH,
    HEALTH_PATH,
)
from audit_exporter.config import Settings
from audit_exporter.domain import (
    AuditAction,
    AuditActorType,
    AuditEvent,
    AuditFilter,
    AuditOutcome,
    AuditPage,
    AuditRecord,
)
from audit_exporter.main import create_app
from audit_exporter.ports import AuditStore

_REPO_ROOT = Path(__file__).resolve().parents[5]
_OPENAPI_PATH = _REPO_ROOT / "source/contracts/openapi/audit-exporter.yaml"
_ASYNCAPI_PATH = _REPO_ROOT / "source/contracts/asyncapi/loandebtors.yaml"


def _openapi() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(_OPENAPI_PATH.read_text(encoding="utf-8")))


def _asyncapi() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(_ASYNCAPI_PATH.read_text(encoding="utf-8")))


def test_api_paths_match_contract() -> None:
    """HTTP-константы совпадают с путями OpenAPI."""
    contract = _openapi()

    assert set(contract["paths"]) == {HEALTH_PATH, AUDIT_RECORDS_PATH, AUDIT_RECORD_PATH}


def test_generated_openapi_matches_contract_operation_ids() -> None:
    """Сгенерированная схема сохраняет operationId из контракта."""
    contract = _openapi()
    app = create_app(
        Settings(
            service_name="audit_exporter",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    generated = app.openapi()

    for path in (AUDIT_RECORDS_PATH, AUDIT_RECORD_PATH):
        assert generated["paths"][path]["get"]["operationId"] == contract["paths"][path]["get"]["operationId"]


def test_audit_event_fields_match_contract() -> None:
    """Доменное событие содержит все поля из OpenAPI, включая nullable."""
    schema = _openapi()["components"]["schemas"]["AuditEvent"]
    expected = set(schema["required"]) | {"campaign_id", "message_id", "channel", "trace_id"}

    assert {field.name for field in fields(AuditEvent)} == expected


def test_audit_record_and_page_fields_match_contract() -> None:
    """Запись и страница журнала совпадают с контрактом."""
    schemas = _openapi()["components"]["schemas"]

    assert {field.name for field in fields(AuditRecord)} == set(schemas["AuditRecord"]["required"])
    assert {field.name for field in fields(AuditPage)} == set(schemas["AuditPage"]["required"])


def test_audit_filter_fields_match_query_parameters() -> None:
    """Поля фильтра совпадают с query-параметрами контракта."""
    contract = _openapi()
    parameters = contract["paths"][AUDIT_RECORDS_PATH]["get"]["parameters"]
    expected = set()
    for reference in parameters:
        name = reference["$ref"].rsplit("/", 1)[-1]
        expected.add(contract["components"]["parameters"][name]["name"])

    assert {field.name for field in fields(AuditFilter)} == expected


def test_enums_match_contract() -> None:
    """Значения enum совпадают с OpenAPI и AsyncAPI."""
    schemas = _openapi()["components"]["schemas"]
    async_schemas = _asyncapi()["components"]["schemas"]

    assert set(schemas["AuditAction"]["enum"]) == {action.value for action in AuditAction}
    assert set(async_schemas["AuditAction"]["enum"]) == {action.value for action in AuditAction}
    assert set(schemas["AuditActorType"]["enum"]) == {value.value for value in AuditActorType}
    assert set(schemas["AuditOutcome"]["enum"]) == {value.value for value in AuditOutcome}


def test_audit_store_exposes_only_append_and_read_operations() -> None:
    """Порт предоставляет добавление и чтение, без изменения и удаления."""
    assert hasattr(AuditStore, "append")
    assert hasattr(AuditStore, "query")
    assert hasattr(AuditStore, "get_by_event_id")
    assert not hasattr(AuditStore, "update")
    assert not hasattr(AuditStore, "delete")


def test_audit_service_examples_include_exporter() -> None:
    """Схема service допускает audit_exporter для self-audit."""
    schemas = _openapi()["components"]["schemas"]
    async_schemas = _asyncapi()["components"]["schemas"]

    assert "audit_exporter" in schemas["AuditEvent"]["properties"]["service"]["examples"]
    assert "audit_exporter" in async_schemas["AuditEventPayload"]["properties"]["service"]["examples"]
