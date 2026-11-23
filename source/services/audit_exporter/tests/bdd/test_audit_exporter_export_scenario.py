"""BDD-сценарий выгрузки журнала и self-audit."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pytest_bdd import given, scenario, then, when

from audit_exporter.adapters.http.constants import AUDIT_RECORDS_PATH
from audit_exporter.application.audit_reader import AuditReader
from audit_exporter.config import Settings
from audit_exporter.domain import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditOutcome,
    AuditPage,
    AuditRecord,
    CampaignId,
)
from audit_exporter.main import create_app
from audit_exporter.ports import AuditStore

pytestmark = pytest.mark.bdd

_EVENT_ID = UUID("3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d")
_CAMPAIGN_ID = UUID("5a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d")
_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class FakeClock:
    """Часы с фиксированным временем."""

    def now(self) -> datetime:
        """Вернуть фиксированное время."""
        return _NOW


class ExportStore:
    """Хранилище для сценария выгрузки."""

    def __init__(self) -> None:
        """Создать пустой журнал."""
        self.records: list[AuditRecord] = []

    async def append(self, event: AuditEvent) -> None:
        """Добавить событие с очередным sequence."""
        self.records.append(AuditRecord(sequence=len(self.records) + 1, event=event, ingested_at=_NOW))

    async def query(self, filters: object) -> AuditPage:
        """Вернуть все записи без фильтрации."""
        return AuditPage(items=tuple(self.records), next_cursor=None)

    async def get_by_event_id(self, event_id: AuditEventId) -> AuditRecord | None:
        """Вернуть запись по event_id."""
        for record in self.records:
            if record.event.event_id == event_id:
                return record
        return None


def _record() -> AuditRecord:
    event = AuditEvent(
        event_id=AuditEventId(_EVENT_ID),
        occurred_at=_NOW,
        service="notifications",
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier="notifications"),
        action=AuditAction.MESSAGE_SENT,
        entity_type="message",
        entity_id=str(_EVENT_ID),
        campaign_id=CampaignId(_CAMPAIGN_ID),
        message_id=None,
        channel=None,
        outcome=AuditOutcome.SUCCESS,
        details={"provider": "mailpit"},
        correlation_id="corr-1",
        trace_id=None,
    )
    return AuditRecord(sequence=1, event=event, ingested_at=_NOW)


@pytest.fixture
def store() -> ExportStore:
    """Создать журнал с одной записью."""
    store = ExportStore()
    store.records.append(_record())
    return store


@pytest.fixture
def client(store: ExportStore) -> Iterator[TestClient]:
    """Создать клиент с реальным AuditReader поверх fake store."""
    app = create_app(
        Settings(
            service_name="audit_exporter",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    app.state.audit_reader = AuditReader(cast(AuditStore, store), FakeClock())
    with TestClient(app) as test_client:
        yield test_client


@scenario("features/audit_export.feature", "Администратор получает первую страницу журнала")
def test_first_page_is_exported() -> None:
    """Сценарий выполняется шагами ниже."""


@given("в журнале есть запись о сообщении")
def journal_has_record(store: ExportStore) -> None:
    """Проверить подготовленную запись."""
    assert len(store.records) == 1


@when("администратор запрашивает первую страницу", target_fixture="response")
def request_first_page(client: TestClient) -> Response:
    """Запросить первую страницу журнала."""
    response: Response = client.get(AUDIT_RECORDS_PATH)
    return response


@then("ответ содержит одну запись")
def response_has_one_record(response: Response) -> None:
    """Проверить ответ API."""
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["event"]["event_id"] == str(_EVENT_ID)


@then('в журнале появляется событие "audit.exported"')
def journal_has_export_event(store: ExportStore) -> None:
    """Проверить self-audit."""
    assert len(store.records) == 2
    assert store.records[-1].event.action is AuditAction.AUDIT_EXPORTED
    assert store.records[-1].event.service == "audit_exporter"
