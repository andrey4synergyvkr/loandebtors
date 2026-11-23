"""Репозиторий отметок об отмене кампаний на SQLAlchemy."""

from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.adapters.persistence.models import CancelledCampaignRow
from scheduler.domain import CampaignId


class SqlAlchemyCancelledCampaignRepository:
    """Хранит отметки об отмене в схеме scheduler в текущей сессии."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def add(self, campaign_id: CampaignId, occurred_at: datetime) -> None:
        """Идемпотентно сохранить время отмены кампании."""
        statement = (
            insert(CancelledCampaignRow)
            .values(campaign_id=campaign_id, occurred_at=occurred_at)
            .on_conflict_do_nothing(index_elements=["campaign_id"])
        )
        await self._session.execute(statement)

    async def get_occurred_at(self, campaign_id: CampaignId) -> datetime | None:
        """Вернуть время отмены кампании или None."""
        statement = select(CancelledCampaignRow.occurred_at).where(
            CancelledCampaignRow.campaign_id == campaign_id
        )
        return cast(datetime | None, await self._session.scalar(statement))
