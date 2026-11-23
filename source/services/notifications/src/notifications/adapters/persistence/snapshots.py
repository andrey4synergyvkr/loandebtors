"""Репозиторий снимков должников на SQLAlchemy."""

from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.adapters.persistence.debtor_json import (
    contacts_from_json,
    contacts_to_json,
    debts_from_json,
    debts_to_json,
)
from notifications.adapters.persistence.models import DebtorSnapshotRow
from notifications.domain import (
    AbsDebtor,
    CampaignId,
    DebtorId,
    DebtorSnapshot,
)


class SqlAlchemyDebtorSnapshotRepository:
    """Хранит полный снимок выборки должников кампании."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def replace_for_campaign(
        self,
        campaign_id: CampaignId,
        snapshots: Sequence[DebtorSnapshot],
    ) -> None:
        """Атомарно заменить снимок должников кампании."""
        await self._session.execute(
            delete(DebtorSnapshotRow).where(DebtorSnapshotRow.campaign_id == campaign_id)
        )
        self._session.add_all(
            [
                DebtorSnapshotRow(
                    campaign_id=campaign_id,
                    debtor_id=snapshot.debtor.debtor_id,
                    full_name=snapshot.debtor.full_name,
                    contacts=contacts_to_json(snapshot.debtor.contacts),
                    debts=debts_to_json(snapshot.debtor.debts),
                    fetched_at=snapshot.fetched_at,
                )
                for snapshot in snapshots
            ]
        )
        await self._session.flush()

    async def count(self, campaign_id: CampaignId) -> int:
        """Вернуть число сохраненных должников кампании."""
        statement = (
            select(func.count())
            .select_from(DebtorSnapshotRow)
            .where(DebtorSnapshotRow.campaign_id == campaign_id)
        )
        return int((await self._session.scalar(statement)) or 0)

    async def list(
        self,
        campaign_id: CampaignId,
        offset: int,
        limit: int,
    ) -> Sequence[DebtorSnapshot]:
        """Вернуть страницу снимков должников."""
        statement = (
            select(DebtorSnapshotRow)
            .where(DebtorSnapshotRow.campaign_id == campaign_id)
            .order_by(DebtorSnapshotRow.debtor_id)
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.scalars(statement)).all()
        return [_to_domain(row) for row in rows]


def _to_domain(row: DebtorSnapshotRow) -> DebtorSnapshot:
    """Преобразовать ORM-запись в доменный снимок."""
    return DebtorSnapshot(
        campaign_id=CampaignId(row.campaign_id),
        debtor=AbsDebtor(
            debtor_id=DebtorId(row.debtor_id),
            full_name=row.full_name,
            contacts=contacts_from_json(row.contacts),
            debts=debts_from_json(row.debts),
        ),
        fetched_at=row.fetched_at,
    )
