"""Проверка read-only API журнала аудита."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from audit_exporter.adapters.http.constants import AUDIT_RECORD_PATH, AUDIT_RECORDS_PATH
from audit_exporter.adapters.http.problems import (
    INTERNAL_ERROR_CODE,
    INTERNAL_ERROR_TYPE,
    NOT_FOUND_CODE,
    NOT_FOUND_TYPE,
    PROBLEM_MEDIA_TYPE,
    VALIDATION_CODE,
    VALIDATION_TYPE,
)
from audit_exporter.application.audit_reader import RequestContext
from audit_exporter.config import Settings
from audit_exporter.domain import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditFilter,
    AuditOutcome,
    AuditPage,
    AuditRecord,
    CampaignId,
    Channel,
    NotFoundError,
    ValidationError,
)
from audit_exporter.main import create_app

_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
_EVENT_ID = UUID("3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d")
_CAMPAIGN_ID = UUID("5a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d")


class FakeReader:
    """Читатель с заранее заданным ответом."""

    def __init__(
        self,
        page: AuditPage | None = None,
        record: AuditRecord | None = None,
        error: Exception | None = None,
    ) -> None:
        """Сохранить ответ и ошибку."""
        self.page = page or AuditPage(items=(), next_cursor=None)
        self.record = record
        self.error = error
        self.filters: AuditFilter | None = None
        self.context: RequestContext | None = None
        self.requested_event_id: AuditEventId | None = None

    async def list_records(self, filters: AuditFilter, context: RequestContext) -> AuditPage:
        """Вернуть заданную страницу или ошибку."""
        if filters.cursor == "bad":
            raise ValidationError("Некорректный курсор")
        if self.error is not None:
            raise self.error
        self.filters = filters
        self.context = context
        return self.page

    async def get_record(
        self,
        event_id: AuditEventId,
        context: RequestContext | None = None,
    ) -> AuditRecord:
        """Вернуть заданную запись или ошибку."""
        if self.error is not None:
            raise self.error
        self.requested_event_id = event_id
        if self.record is None:
            raise NotFoundError("Запись журнала не найдена")
        return self.record


def _event() -> AuditEvent:
    return AuditEvent(
        event_id=AuditEventId(_EVENT_ID),
        occurred_at=_NOW,
        service="notifications",
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier="notifications"),
        action=AuditAction.MESSAGE_SENT,
        entity_type="message",
        entity_id=str(_EVENT_ID),
        campaign_id=CampaignId(_CAMPAIGN_ID),
        message_id=None,
        channel=Channel("email"),
        outcome=AuditOutcome.SUCCESS,
        details={"provider": "mailpit"},
        correlation_id="corr-1",
        trace_id=None,
    )


def _record() -> AuditRecord:
    return AuditRecord(sequence=1, event=_event(), ingested_at=_NOW)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Создать тестовый клиент с пустым читателем."""
    app = create_app(
        Settings(
            service_name="audit_exporter",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    app.state.audit_reader = FakeReader()
    with TestClient(app) as test_client:
        yield test_client


def test_list_records_returns_page(client: TestClient) -> None:
    """Страница журнала отдаётся в формате контракта."""
    reader = FakeReader(page=AuditPage(items=(_record(),), next_cursor="next"))
    client.app.state.audit_reader = reader  # type: ignore[attr-defined]

    response = client.get(
        AUDIT_RECORDS_PATH,
        params={
            "campaign_id": str(_CAMPAIGN_ID),
            "channel": "email",
            "action": "message.sent",
            "occurred_from": "2026-11-01T00:00:00Z",
            "occurred_to": "2026-11-30T00:00:00Z",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["next_cursor"] == "next"
    assert payload["items"][0]["sequence"] == 1
    assert payload["items"][0]["event"]["event_id"] == str(_EVENT_ID)
    assert payload["items"][0]["event"]["action"] == "message.sent"
    assert payload["items"][0]["event"]["details"] == {"provider": "mailpit"}
    assert reader.filters is not None
    assert reader.filters.campaign_id == _CAMPAIGN_ID
    assert reader.filters.channel == "email"
    assert reader.filters.action is AuditAction.MESSAGE_SENT
    assert reader.filters.limit == 10
    assert reader.context is not None
    assert reader.context.correlation_id


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 1001},
        {"campaign_id": "not-a-uuid"},
        {"channel": "Email!"},
        {"action": "unknown.action"},
        {"occurred_from": "2026-11-22T12:00:00"},
        {"cursor": "bad"},
    ],
)
def test_list_records_returns_validation_problem(client: TestClient, params: dict[str, Any]) -> None:
    """Невалидные параметры дают 422 Problem."""
    response = client.get(AUDIT_RECORDS_PATH, params=params)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    payload = response.json()
    assert payload["type"] == VALIDATION_TYPE
    assert payload["code"] == VALIDATION_CODE
    assert payload["status"] == 422
    assert payload["instance"] == AUDIT_RECORDS_PATH


def test_list_records_maps_domain_validation_error(client: TestClient) -> None:
    """Ошибка домена из читателя даёт 422 Problem."""
    client.app.state.audit_reader = FakeReader(error=ValidationError("Некорректный фильтр"))  # type: ignore[attr-defined]

    response = client.get(AUDIT_RECORDS_PATH)

    assert response.status_code == 422
    assert response.json()["type"] == VALIDATION_TYPE


def test_get_record_returns_record(client: TestClient) -> None:
    """Запись отдаётся по идентификатору события."""
    reader = FakeReader(record=_record())
    client.app.state.audit_reader = reader  # type: ignore[attr-defined]

    response = client.get(AUDIT_RECORD_PATH.format(event_id=_EVENT_ID))

    assert response.status_code == 200
    payload = response.json()
    assert payload["sequence"] == 1
    assert payload["event"]["event_id"] == str(_EVENT_ID)
    assert payload["event"]["correlation_id"] == "corr-1"
    assert reader.requested_event_id == _EVENT_ID


def test_get_record_returns_not_found_problem(client: TestClient) -> None:
    """Отсутствующая запись даёт 404 Problem."""
    response = client.get(AUDIT_RECORD_PATH.format(event_id=_EVENT_ID))

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    payload = response.json()
    assert payload["type"] == NOT_FOUND_TYPE
    assert payload["code"] == NOT_FOUND_CODE
    assert payload["status"] == 404


def test_get_record_rejects_invalid_uuid(client: TestClient) -> None:
    """Невалидный UUID в пути даёт 422 Problem."""
    response = client.get(AUDIT_RECORD_PATH.format(event_id="not-a-uuid"))

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.json()["type"] == VALIDATION_TYPE


def test_unhandled_error_returns_internal_problem() -> None:
    """Непредвиденная ошибка отдаётся как 500 Problem."""
    app = create_app(
        Settings(
            service_name="audit_exporter",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    app.state.audit_reader = FakeReader(error=RuntimeError("boom"))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get(AUDIT_RECORDS_PATH)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    payload = response.json()
    assert payload["type"] == INTERNAL_ERROR_TYPE
    assert payload["code"] == INTERNAL_ERROR_CODE
