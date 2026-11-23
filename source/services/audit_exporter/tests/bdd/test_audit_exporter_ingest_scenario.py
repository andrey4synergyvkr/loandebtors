"""BDD-сценарии приёма audit.event."""

import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from pytest_bdd import given, scenario, then, when

from audit_exporter.application.audit_ingest import AuditIngestService
from audit_exporter.domain import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditEventId,
    AuditOutcome,
    AuditPage,
    AuditRecord,
)
from audit_exporter.ports import AuditStore

pytestmark = pytest.mark.bdd

_EVENT_ID = UUID("3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d")
_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class InMemoryStore:
    """Хранилище с дедупликацией по event_id."""

    def __init__(self) -> None:
        """Создать пустой журнал."""
        self.records: list[AuditRecord] = []

    async def append(self, event: AuditEvent) -> None:
        """Добавить событие, если его еще нет."""
        if any(record.event.event_id == event.event_id for record in self.records):
            return
        self.records.append(AuditRecord(sequence=len(self.records) + 1, event=event, ingested_at=_NOW))

    async def query(self, filters: object) -> AuditPage:
        """Чтение в сценарии приёма не используется."""
        raise NotImplementedError

    async def get_by_event_id(self, event_id: AuditEventId) -> AuditRecord | None:
        """Вернуть запись по event_id."""
        for record in self.records:
            if record.event.event_id == event_id:
                return record
        return None


def _event() -> AuditEvent:
    return AuditEvent(
        event_id=AuditEventId(_EVENT_ID),
        occurred_at=_NOW,
        service="notifications",
        actor=AuditActor(type=AuditActorType.SYSTEM, identifier="notifications"),
        action=AuditAction.MESSAGE_SENT,
        entity_type="message",
        entity_id=str(_EVENT_ID),
        campaign_id=None,
        message_id=None,
        channel=None,
        outcome=AuditOutcome.SUCCESS,
        details={"provider": "mailpit"},
        correlation_id="corr-1",
        trace_id=None,
    )


@pytest.fixture
def store() -> InMemoryStore:
    """Создать пустое хранилище."""
    return InMemoryStore()


@pytest.fixture
def service(store: InMemoryStore) -> AuditIngestService:
    """Создать сервис приёма с in-memory хранилищем."""
    return AuditIngestService(cast(AuditStore, store))


@scenario("features/audit_ingest.feature", "Событие audit.event записывается в журнал")
def test_audit_event_is_stored() -> None:
    """Сценарий выполняется шагами ниже."""


@scenario("features/audit_ingest.feature", "Повторное событие не создает вторую запись")
def test_duplicate_audit_event_is_ignored() -> None:
    """Сценарий выполняется шагами ниже."""


@given('подготовлено событие audit.event с действием "message.sent"', target_fixture="event")
def prepared_event() -> AuditEvent:
    """Подготовить событие."""
    return _event()


@given("событие audit.event уже записано", target_fixture="event")
def stored_event(service: AuditIngestService) -> AuditEvent:
    """Записать событие заранее."""
    event = _event()
    asyncio.run(service.handle(event))
    return event


@when("сервис принимает событие")
def ingest_event(service: AuditIngestService, event: AuditEvent) -> None:
    """Передать событие в сервис приёма."""
    asyncio.run(service.handle(event))


@when("сервис принимает то же событие повторно")
def ingest_same_event(service: AuditIngestService, event: AuditEvent) -> None:
    """Передать то же событие повторно."""
    asyncio.run(service.handle(event))


@then('в журнале есть запись с действием "message.sent" и источником "notifications"')
def assert_record_exists(store: InMemoryStore) -> None:
    """Проверить запись журнала."""
    assert len(store.records) == 1
    event = store.records[0].event
    assert event.action is AuditAction.MESSAGE_SENT
    assert event.service == "notifications"


@then("в журнале остается одна запись")
def assert_single_record(store: InMemoryStore) -> None:
    """Проверить дедупликацию."""
    assert len(store.records) == 1
