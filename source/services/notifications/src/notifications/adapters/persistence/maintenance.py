"""SQLAlchemy-реализация обслуживания и восстановления."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.adapters.messaging.constants import RoutingKey
from notifications.adapters.persistence.campaigns import _to_domain as campaign_to_domain
from notifications.adapters.persistence.messages import _to_domain as message_to_domain
from notifications.adapters.persistence.models import (
    CampaignRow,
    MessageAttemptRow,
    MessageRow,
    OutboxRow,
)
from notifications.domain import Campaign, CampaignStatus, MessageStatus, NotificationMessage
from notifications.ports.maintenance import ExhaustedMessageCommand

NON_TERMINAL_STATUSES = (
    MessageStatus.PENDING.value,
    MessageStatus.QUEUED.value,
)


class SqlAlchemyMaintenanceStore:
    """Выполняет retention и находит зависшие состояния."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def delete_published_outbox_before(self, cutoff: datetime) -> int:
        """Удалить опубликованные записи outbox старше cutoff."""
        result = await self._session.execute(
            delete(OutboxRow).where(
                OutboxRow.published_at.is_not(None),
                OutboxRow.published_at < cutoff,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def delete_attempts_before(self, cutoff: datetime) -> int:
        """Удалить попытки отправки старше cutoff."""
        result = await self._session.execute(
            delete(MessageAttemptRow).where(MessageAttemptRow.occurred_at < cutoff)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def list_retry_due(
        self,
        now: datetime,
        limit: int,
    ) -> Sequence[NotificationMessage]:
        """Вернуть сообщения с наступившим временем повтора."""
        statement = (
            select(MessageRow)
            .where(
                MessageRow.status == MessageStatus.QUEUED.value,
                MessageRow.next_attempt_at.is_not(None),
                MessageRow.next_attempt_at <= now,
            )
            .order_by(MessageRow.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.scalars(statement)).all()
        return [message_to_domain(row) for row in rows]

    async def list_stuck_campaigns(
        self,
        before: datetime,
        limit: int,
    ) -> Sequence[Campaign]:
        """Вернуть running-кампании без созданных сообщений."""
        statement = (
            select(CampaignRow)
            .where(
                CampaignRow.status == CampaignStatus.RUNNING.value,
                CampaignRow.messages_created_at.is_(None),
                CampaignRow.started_at.is_not(None),
                CampaignRow.started_at < before,
            )
            .order_by(CampaignRow.started_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.scalars(statement)).all()
        return [campaign_to_domain(row) for row in rows]

    async def list_completable_campaigns(self, limit: int) -> Sequence[Campaign]:
        """Вернуть running-кампании без незавершенных сообщений."""
        pending_exists = exists().where(
            MessageRow.campaign_id == CampaignRow.id,
            MessageRow.status.in_(NON_TERMINAL_STATUSES),
        )
        statement = (
            select(CampaignRow)
            .where(
                CampaignRow.status == CampaignStatus.RUNNING.value,
                CampaignRow.messages_created_at.is_not(None),
                ~pending_exists,
            )
            .order_by(CampaignRow.started_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.scalars(statement)).all()
        return [campaign_to_domain(row) for row in rows]

    async def list_exhausted_message_send(
        self,
        max_attempts: int,
        limit: int,
    ) -> Sequence[ExhaustedMessageCommand]:
        """Вернуть команды message.send с исчерпанными попытками outbox."""
        statement = (
            select(OutboxRow)
            .where(
                OutboxRow.event_type == RoutingKey.MESSAGE_SEND.value,
                OutboxRow.published_at.is_(None),
                OutboxRow.failed_at.is_(None),
                OutboxRow.attempts >= max_attempts,
            )
            .order_by(OutboxRow.available_at, OutboxRow.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.scalars(statement)).all()
        exhausted: list[ExhaustedMessageCommand] = []
        for row in rows:
            raw_message_id = row.payload.get("message_id")
            if raw_message_id is None:
                continue
            try:
                message_id = UUID(str(raw_message_id))
            except ValueError:
                continue
            exhausted.append(ExhaustedMessageCommand(outbox_id=UUID(str(row.id)), message_id=message_id))
        return exhausted

    async def mark_outbox_failed(self, outbox_id: UUID, failed_at: datetime) -> bool:
        """Зафиксировать окончательный отказ публикации записи outbox."""
        statement = (
            update(OutboxRow)
            .where(OutboxRow.id == outbox_id, OutboxRow.failed_at.is_(None))
            .values(failed_at=failed_at)
            .execution_options(synchronize_session=False)
        )
        result = await self._session.execute(statement)
        return bool(getattr(result, "rowcount", 0))
