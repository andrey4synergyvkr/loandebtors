"""Порт транзакционного outbox."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from scheduler.domain.audit import AuditEvent
from scheduler.domain.events import CampaignStart


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """Запись outbox, готовая к публикации.

    Attributes:
        id: Идентификатор записи.
        event_type: Тип события для метрик и диагностики.
        exchange: Имя exchange RabbitMQ.
        routing_key: Routing key публикации.
        payload: JSON-совместимое тело сообщения.
        headers: Заголовки сообщения, включая корреляцию.
        occurred_at: Время события в UTC.
        available_at: Время, начиная с которого запись можно публиковать.
        attempts: Сколько попыток публикации уже выполнено.
    """

    id: UUID
    event_type: str
    exchange: str
    routing_key: str
    payload: Mapping[str, object]
    headers: Mapping[str, str]
    occurred_at: datetime
    available_at: datetime
    attempts: int


@dataclass(frozen=True, slots=True)
class OutboxBatchResult:
    """Результат обработки пачки outbox.

    Attributes:
        published: Сколько записей опубликовано.
        failed: Сколько публикаций завершилось ошибкой.
    """

    published: int
    failed: int


type PublishCallback = Callable[[OutboxEntry], Awaitable[None]]


class OutboxStore(Protocol):
    """Хранилище outbox с выборкой готовых записей."""

    async def process_ready(
        self,
        limit: int,
        now: datetime,
        publish: PublishCallback,
    ) -> OutboxBatchResult:
        """Опубликовать готовые записи и обновить их состояние."""
        ...


class EventOutbox(Protocol):
    """Запись исходящих событий в outbox текущей транзакции."""

    async def add_campaign_start(
        self,
        event: CampaignStart,
        *,
        correlation_id: str,
        trace_id: str | None,
    ) -> None:
        """Добавить команду campaign.start."""
        ...

    async def add_audit(self, event: AuditEvent) -> None:
        """Добавить audit.event."""
        ...
