"""Репозиторий кампаний на SQLAlchemy."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.adapters.persistence.campaign_json import (
    schedule_from_json,
    schedule_to_json,
    selection_from_json,
    selection_to_json,
)
from notifications.adapters.persistence.models import CampaignRow, MessageRow
from notifications.domain import (
    Campaign,
    CampaignId,
    CampaignStatus,
    Channel,
    ConflictError,
    MessageStatus,
    NotFoundError,
    TemplateKey,
)


class SqlAlchemyCampaignRepository:
    """Читает и сохраняет кампании в схеме notification."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def add(self, campaign: Campaign) -> None:
        """Создать новую кампанию.

        Raises:
            ConflictError: Идентификатор уже занят или шаблон не существует.
        """
        row = CampaignRow(id=campaign.id)
        _apply(row, campaign)
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError(f"Кампания {campaign.id} не может быть создана") from exc

    async def get(self, campaign_id: CampaignId) -> Campaign | None:
        """Вернуть кампанию или None."""
        row = await self._session.get(CampaignRow, campaign_id)
        return None if row is None else _to_domain(row)

    async def save(self, campaign: Campaign) -> None:
        """Сохранить изменения существующей кампании.

        Raises:
            NotFoundError: Кампания отсутствует.
            ConflictError: Нарушено ограничение базы.
        """
        row = await self._session.get(CampaignRow, campaign.id)
        if row is None:
            raise NotFoundError(f"Кампания {campaign.id} не найдена")
        _apply(row, campaign)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError(f"Кампания {campaign.id} не может быть сохранена") from exc

    async def list(
        self,
        status: CampaignStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Campaign]:
        """Вернуть страницу кампаний."""
        statement = select(CampaignRow)
        if status is not None:
            statement = statement.where(CampaignRow.status == status.value)
        statement = (
            statement.order_by(CampaignRow.created_at.desc(), CampaignRow.id).limit(limit).offset(offset)
        )
        rows = (await self._session.scalars(statement)).all()
        return [_to_domain(row) for row in rows]

    async def count(self, status: CampaignStatus | None = None) -> int:
        """Вернуть число кампаний."""
        statement = select(func.count()).select_from(CampaignRow)
        if status is not None:
            statement = statement.where(CampaignRow.status == status.value)
        return int((await self._session.scalar(statement)) or 0)

    async def try_advisory_lock(self, campaign_id: CampaignId) -> bool:
        """Попробовать взять транзакционную advisory-блокировку кампании."""
        statement = select(func.pg_try_advisory_xact_lock(func.hashtextextended(str(campaign_id), 0)))
        return bool(await self._session.scalar(statement))

    async def complete_if_running(self, campaign_id: CampaignId, now: datetime) -> bool:
        """Атомарно завершить running-кампанию без незавершенных сообщений."""
        pending_exists = exists().where(
            MessageRow.campaign_id == campaign_id,
            MessageRow.status.in_((MessageStatus.PENDING.value, MessageStatus.QUEUED.value)),
        )
        statement = (
            update(CampaignRow)
            .where(
                CampaignRow.id == campaign_id,
                CampaignRow.status == CampaignStatus.RUNNING.value,
                ~pending_exists,
            )
            .values(
                status=CampaignStatus.COMPLETED.value,
                finished_at=now,
                updated_at=now,
            )
            .returning(CampaignRow.id)
        )
        return (await self._session.scalar(statement)) is not None


def _apply(row: CampaignRow, campaign: Campaign) -> None:
    """Перенести доменные поля кампании в ORM-запись."""
    row.name = campaign.name
    row.channel = campaign.channel
    row.template_key = campaign.template_key
    row.template_version = campaign.template_version
    row.status = campaign.status.value
    row.selection = selection_to_json(campaign.selection)
    row.schedule = schedule_to_json(campaign.schedule)
    row.selected_debtors = campaign.selected_debtors
    row.selection_expected = campaign.selection_expected
    row.selection_completed_at = campaign.selection_completed_at
    row.messages_created_at = campaign.messages_created_at
    row.created_at = campaign.created_at
    row.updated_at = campaign.updated_at
    row.scheduled_at = campaign.scheduled_at
    row.started_at = campaign.started_at
    row.finished_at = campaign.finished_at
    row.cancelled_at = campaign.cancelled_at
    row.failure_reason = campaign.failure_reason


def _to_domain(row: CampaignRow) -> Campaign:
    """Преобразовать ORM-запись в доменную кампанию."""
    return Campaign(
        id=CampaignId(UUID(str(row.id))),
        name=row.name,
        channel=Channel(row.channel),
        template_key=TemplateKey(row.template_key),
        template_version=row.template_version,
        status=CampaignStatus(row.status),
        selection=selection_from_json(row.selection),
        schedule=schedule_from_json(row.schedule),
        selected_debtors=row.selected_debtors,
        selection_expected=row.selection_expected,
        selection_completed_at=row.selection_completed_at,
        messages_created_at=row.messages_created_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        scheduled_at=row.scheduled_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        cancelled_at=row.cancelled_at,
        failure_reason=row.failure_reason,
    )
