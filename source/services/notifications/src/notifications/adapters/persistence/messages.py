"""Репозиторий сообщений кампании на SQLAlchemy."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.adapters.persistence.models import MessageRow
from notifications.domain import (
    CampaignId,
    Channel,
    ConflictError,
    DebtorId,
    IdempotencyKey,
    MessageId,
    MessageStatus,
    NotificationMessage,
    Recipient,
    TemplateKey,
)


class SqlAlchemyNotificationMessageRepository:
    """Читает и сохраняет сообщения кампании."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def add_many(self, messages: Sequence[NotificationMessage]) -> None:
        """Создать сообщения пачкой.

        Raises:
            ConflictError: Нарушен ключ дедупликации сообщения.
        """
        self._session.add_all([_to_row(message) for message in messages])
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError("Сообщения кампании нарушают ключ дедупликации") from exc

    async def get(self, message_id: MessageId) -> NotificationMessage | None:
        """Вернуть сообщение или None."""
        row = await self._session.get(MessageRow, message_id)
        return None if row is None else _to_domain(row)

    async def save(self, message: NotificationMessage) -> None:
        """Сохранить изменения состояния сообщения."""
        row = await self._session.get(MessageRow, message.id)
        if row is None:
            self._session.add(_to_row(message))
        else:
            _apply(row, message)
        await self._session.flush()

    async def list_by_campaign(
        self,
        campaign_id: CampaignId,
        status: MessageStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NotificationMessage]:
        """Вернуть страницу сообщений кампании."""
        statement = select(MessageRow).where(MessageRow.campaign_id == campaign_id)
        if status is not None:
            statement = statement.where(MessageRow.status == status.value)
        statement = statement.order_by(MessageRow.created_at, MessageRow.id).limit(limit).offset(offset)
        rows = (await self._session.scalars(statement)).all()
        return [_to_domain(row) for row in rows]

    async def count_by_campaign(
        self,
        campaign_id: CampaignId,
        status: MessageStatus | None = None,
    ) -> int:
        """Вернуть число сообщений кампании."""
        statement = select(func.count()).select_from(MessageRow).where(MessageRow.campaign_id == campaign_id)
        if status is not None:
            statement = statement.where(MessageRow.status == status.value)
        return int((await self._session.scalar(statement)) or 0)

    async def count_not_terminal(self, campaign_id: CampaignId) -> int:
        """Вернуть число сообщений, которые еще не завершены."""
        terminal = (
            MessageStatus.SENT.value,
            MessageStatus.FAILED.value,
            MessageStatus.CANCELLED.value,
        )
        statement = (
            select(func.count())
            .select_from(MessageRow)
            .where(
                MessageRow.campaign_id == campaign_id,
                MessageRow.status.not_in(terminal),
            )
        )
        return int((await self._session.scalar(statement)) or 0)

    async def cancel_pending(self, campaign_id: CampaignId) -> int:
        """Перевести неотправленные сообщения кампании в cancelled."""
        statement = (
            update(MessageRow)
            .where(
                MessageRow.campaign_id == campaign_id,
                MessageRow.status.in_((MessageStatus.PENDING.value, MessageStatus.QUEUED.value)),
            )
            .values(status=MessageStatus.CANCELLED.value, next_attempt_at=None)
            .execution_options(synchronize_session=False)
        )
        result = await self._session.execute(statement)
        return int(getattr(result, "rowcount", 0) or 0)


def _to_row(message: NotificationMessage) -> MessageRow:
    """Создать ORM-запись сообщения."""
    row = MessageRow(id=message.id)
    _apply(row, message)
    return row


def _apply(row: MessageRow, message: NotificationMessage) -> None:
    """Перенести доменные поля сообщения в ORM-запись."""
    row.campaign_id = message.campaign_id
    row.debtor_id = message.debtor_id
    row.channel = message.channel
    row.template_key = message.template_key
    row.template_version = message.template_version
    row.variables = dict(message.variables)
    row.recipient = {
        "channel": message.recipient.channel,
        "address": message.recipient.address,
    }
    row.idempotency_key = message.idempotency_key
    row.status = message.status.value
    row.attempt_count = message.attempt_count
    row.max_attempts = message.max_attempts
    row.created_at = message.created_at
    row.queued_at = message.queued_at
    row.last_attempt_at = message.last_attempt_at
    row.sent_at = message.sent_at
    row.failed_at = message.failed_at
    row.next_attempt_at = message.next_attempt_at
    row.last_error_code = message.last_error_code
    row.last_error_message = message.last_error_message


def _to_domain(row: MessageRow) -> NotificationMessage:
    """Преобразовать ORM-запись в доменное сообщение."""
    return NotificationMessage(
        id=MessageId(UUID(str(row.id))),
        campaign_id=CampaignId(UUID(str(row.campaign_id))),
        debtor_id=DebtorId(row.debtor_id),
        channel=Channel(row.channel),
        template_key=TemplateKey(row.template_key),
        template_version=row.template_version,
        variables=dict(row.variables),
        recipient=Recipient(
            channel=Channel(row.recipient.get("channel", row.channel)),
            address=str(row.recipient.get("address", "")),
        ),
        idempotency_key=IdempotencyKey(row.idempotency_key),
        status=MessageStatus(row.status),
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        created_at=row.created_at,
        queued_at=row.queued_at,
        last_attempt_at=row.last_attempt_at,
        sent_at=row.sent_at,
        failed_at=row.failed_at,
        next_attempt_at=row.next_attempt_at,
        last_error_code=row.last_error_code,
        last_error_message=row.last_error_message,
    )
