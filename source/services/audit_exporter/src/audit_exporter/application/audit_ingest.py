"""Сценарий приёма audit-события."""

from audit_exporter.domain import AuditEvent, ValidationError
from audit_exporter.ports.audit import AuditStore


class AuditIngestService:
    """Проверяет событие и записывает его в append-only журнал."""

    def __init__(self, store: AuditStore) -> None:
        """Сохранить хранилище журнала."""
        self._store = store

    async def handle(self, event: AuditEvent) -> None:
        """Проверить и записать событие в журнал."""
        self._validate(event)
        await self._store.append(event)

    @staticmethod
    def _validate(event: AuditEvent) -> None:
        """Проверить обязательные поля домена."""
        if event.occurred_at.tzinfo is None:
            raise ValidationError("occurred_at должен содержать часовой пояс")
        if not event.service:
            raise ValidationError("service не должен быть пустым")
        if not event.entity_type:
            raise ValidationError("entity_type не должен быть пустым")
        if not event.entity_id:
            raise ValidationError("entity_id не должен быть пустым")
        if not event.correlation_id:
            raise ValidationError("correlation_id не должен быть пустым")
        for key, value in event.details.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValidationError("details должен содержать только строковые значения")
