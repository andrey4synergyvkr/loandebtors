"""Смоук-тесты контрактов домена и портов Notifications."""

from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from notifications.adapters.http.schemas import (
    CampaignListResponse,
    CampaignResponse,
    CreateCampaignRequest,
    CreateTemplateRequest,
    DebtorSelectionSchema,
    MessageListResponse,
    MessageRecipientSchema,
    MessageResponse,
    ScheduleCampaignRequest,
    ScheduleSpecSchema,
    TemplateListResponse,
    TemplateResponse,
    UpdateCampaignRequest,
    UpdateTemplateStatusRequest,
)
from notifications.adapters.messaging.commands import (
    CampaignStartPayload,
    MessageFailedPayload,
    MessageSentPayload,
)
from notifications.domain import (
    AuditAction,
    Campaign,
    CampaignStatus,
    MessageStatus,
    NotificationCommand,
    NotificationMessage,
    TemplateStatus,
)
from notifications.ports import (
    CampaignRepository,
    MessageAttemptRepository,
    NotificationCommandPublisher,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_OPENAPI_PATH = _REPO_ROOT / "source/contracts/openapi/notifications.yaml"
_ASYNCAPI_PATH = _REPO_ROOT / "source/contracts/asyncapi/loandebtors.yaml"


def _contract(path: Path) -> Any:
    """Загрузить YAML-контракт."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_status_values_are_stable() -> None:
    """Значения статусов соответствуют JSON и БД."""
    assert CampaignStatus.DRAFT.value == "draft"
    assert TemplateStatus.ACTIVE.value == "active"
    assert MessageStatus.SENT.value == "sent"


def test_campaign_contract_contains_required_fields() -> None:
    """Кампания содержит поля жизненного цикла и выборки."""
    assert is_dataclass(Campaign)
    names = {field.name for field in fields(Campaign)}
    assert {
        "id",
        "template_key",
        "template_version",
        "selection",
        "schedule",
        "selected_debtors",
        "selection_expected",
    } <= names


def test_notification_command_contract_contains_exchange_fields() -> None:
    """Команда message.send содержит поля из AsyncAPI."""
    names = {field.name for field in fields(NotificationCommand)}
    assert names == {
        "message_id",
        "campaign_id",
        "debtor_id",
        "channel",
        "template_key",
        "template_version",
        "variables",
        "recipient",
        "idempotency_key",
    }


def test_message_contract_contains_attempt_state() -> None:
    """Сообщение хранит счетчики и время повторных попыток."""
    names = {field.name for field in fields(NotificationMessage)}
    assert {"status", "attempt_count", "max_attempts", "next_attempt_at"} <= names


def test_ports_expose_expected_methods() -> None:
    """Порты объявляют методы, которые реализуют адаптеры."""
    assert hasattr(CampaignRepository, "add")
    assert hasattr(NotificationCommandPublisher, "publish")
    assert hasattr(MessageAttemptRepository, "list_by_message")


def test_template_api_schemas_match_openapi_contract() -> None:
    """Pydantic-схемы шаблонов совпадают с OpenAPI-контрактом."""
    schemas = _contract(_OPENAPI_PATH)["components"]["schemas"]
    assert set(TemplateResponse.model_fields) == set(schemas["Template"]["properties"])
    assert set(TemplateListResponse.model_fields) == set(schemas["TemplateList"]["properties"])
    assert set(CreateTemplateRequest.model_fields) == set(schemas["CreateTemplateRequest"]["properties"])
    assert set(UpdateTemplateStatusRequest.model_fields) == set(
        schemas["UpdateTemplateStatusRequest"]["properties"]
    )


def test_template_status_values_match_openapi_contract() -> None:
    """Статусы шаблона совпадают с enum контракта."""
    schemas = _contract(_OPENAPI_PATH)["components"]["schemas"]
    assert {status.value for status in TemplateStatus} == set(schemas["TemplateStatus"]["enum"])


def test_campaign_api_schemas_match_openapi_contract() -> None:
    """Pydantic-схемы кампаний совпадают с OpenAPI-контрактом."""
    schemas = _contract(_OPENAPI_PATH)["components"]["schemas"]
    assert set(CampaignResponse.model_fields) == set(schemas["Campaign"]["properties"])
    assert set(CampaignListResponse.model_fields) == set(schemas["CampaignList"]["properties"])
    assert set(CreateCampaignRequest.model_fields) == set(schemas["CreateCampaignRequest"]["properties"])
    assert set(UpdateCampaignRequest.model_fields) == set(schemas["UpdateCampaignRequest"]["properties"])
    assert set(DebtorSelectionSchema.model_fields) == set(schemas["DebtorSelection"]["properties"])
    assert set(ScheduleSpecSchema.model_fields) == set(schemas["ScheduleSpec"]["properties"])
    assert set(ScheduleCampaignRequest.model_fields) == set(schemas["ScheduleCampaignRequest"]["properties"])


def test_campaign_status_values_match_openapi_contract() -> None:
    """Статусы кампании совпадают с enum контракта."""
    schemas = _contract(_OPENAPI_PATH)["components"]["schemas"]
    assert {status.value for status in CampaignStatus} == set(schemas["CampaignStatus"]["enum"])


def test_audit_actions_match_asyncapi_contract() -> None:
    """Словарь audit-действий совпадает с AsyncAPI."""
    schemas = _contract(_ASYNCAPI_PATH)["components"]["schemas"]
    assert {action.value for action in AuditAction} == set(schemas["AuditAction"]["enum"])


def test_message_api_schemas_match_openapi_contract() -> None:
    """Pydantic-схемы сообщений совпадают с OpenAPI-контрактом."""
    schemas = _contract(_OPENAPI_PATH)["components"]["schemas"]
    assert set(MessageResponse.model_fields) == set(schemas["Message"]["properties"])
    assert set(MessageListResponse.model_fields) == set(schemas["MessageList"]["properties"])
    assert set(MessageRecipientSchema.model_fields) == set(schemas["Recipient"]["properties"])


def test_consumer_payloads_match_asyncapi_contract() -> None:
    """Схемы входящих сообщений совпадают с AsyncAPI."""
    schemas = _contract(_ASYNCAPI_PATH)["components"]["schemas"]
    assert set(CampaignStartPayload.model_fields) == set(schemas["CampaignStartPayload"]["properties"])
    assert set(MessageSentPayload.model_fields) == set(schemas["MessageSentPayload"]["properties"])
    assert set(MessageFailedPayload.model_fields) == set(schemas["MessageFailedPayload"]["properties"])
