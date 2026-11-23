"""Порт append-only журнала аудита."""

from typing import Protocol

from audit_exporter.domain import AuditEvent, AuditEventId, AuditFilter, AuditPage, AuditRecord


class AuditStore(Protocol):
    """Хранилище журнала без изменения и удаления записей."""

    async def append(self, event: AuditEvent) -> None:
        """Записать событие, повтор по event_id не создаёт новую запись."""
        ...

    async def query(self, filters: AuditFilter) -> AuditPage:
        """Вернуть страницу журнала с фильтрами и курсором."""
        ...

    async def get_by_event_id(self, event_id: AuditEventId) -> AuditRecord | None:
        """Вернуть запись по идентификатору события или None."""
        ...
