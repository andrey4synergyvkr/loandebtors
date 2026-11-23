"""Репозиторий расписаний кампаний на SQLAlchemy."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.adapters.persistence.models import CampaignScheduleRow
from scheduler.domain import CampaignId, CampaignSchedule, ScheduleKind, ScheduleSpec, ScheduleStatus


class SqlAlchemyCampaignScheduleRepository:
    """Хранит расписания в схеме scheduler в текущей сессии."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохранить сессию текущей единицы работы."""
        self._session = session

    async def get(self, campaign_id: CampaignId) -> CampaignSchedule | None:
        """Вернуть расписание кампании или None."""
        row = await self._session.get(CampaignScheduleRow, campaign_id)
        if row is None:
            return None
        return _to_schedule(row)

    async def save(self, schedule: CampaignSchedule) -> None:
        """Создать или обновить расписание."""
        row = await self._session.get(CampaignScheduleRow, schedule.campaign_id)
        if row is None:
            row = CampaignScheduleRow(campaign_id=schedule.campaign_id)
            self._session.add(row)
        row.schedule_kind = schedule.schedule.kind.value
        row.timezone = schedule.schedule.timezone
        row.run_at = schedule.schedule.run_at
        row.cron = schedule.schedule.cron
        row.status = schedule.status.value
        row.next_run_at = schedule.next_run_at
        row.last_triggered_at = schedule.last_triggered_at
        row.correlation_id = schedule.correlation_id
        row.created_at = schedule.created_at
        row.updated_at = schedule.updated_at

    async def list_active(self) -> Sequence[CampaignSchedule]:
        """Вернуть активные расписания для восстановления заданий."""
        statement = (
            select(CampaignScheduleRow)
            .where(CampaignScheduleRow.status == ScheduleStatus.ACTIVE.value)
            .order_by(CampaignScheduleRow.next_run_at.asc().nulls_last())
        )
        rows = (await self._session.scalars(statement)).all()
        return [_to_schedule(row) for row in rows]


def _to_schedule(row: CampaignScheduleRow) -> CampaignSchedule:
    """Преобразовать ORM-запись в доменную сущность."""
    return CampaignSchedule(
        campaign_id=CampaignId(row.campaign_id),
        schedule=ScheduleSpec(
            kind=ScheduleKind(row.schedule_kind),
            timezone=row.timezone,
            run_at=row.run_at,
            cron=row.cron,
        ),
        status=ScheduleStatus(row.status),
        next_run_at=row.next_run_at,
        last_triggered_at=row.last_triggered_at,
        correlation_id=row.correlation_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
