"""Расписание кампании и его переходы состояний."""

from dataclasses import dataclass
from datetime import datetime

from scheduler.domain.enums import ScheduleStatus
from scheduler.domain.ids import CampaignId
from scheduler.domain.values import ScheduleKind, ScheduleSpec


@dataclass(slots=True)
class CampaignSchedule:
    """Расписание запуска кампании.

    Attributes:
        campaign_id: Кампания, которой принадлежит расписание.
        schedule: Правило запуска.
        status: Состояние задания.
        next_run_at: Ближайший плановый запуск.
        last_triggered_at: Время последнего срабатывания.
        correlation_id: Корреляция исходной команды campaign.scheduled.
        created_at: Время создания расписания.
        updated_at: Время последнего изменения.
    """

    campaign_id: CampaignId
    schedule: ScheduleSpec
    status: ScheduleStatus
    next_run_at: datetime | None
    last_triggered_at: datetime | None
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        campaign_id: CampaignId,
        schedule: ScheduleSpec,
        now: datetime,
        correlation_id: str | None = None,
    ) -> "CampaignSchedule":
        """Создать активное расписание кампании."""
        return cls(
            campaign_id=campaign_id,
            schedule=schedule,
            status=ScheduleStatus.ACTIVE,
            next_run_at=None,
            last_triggered_at=None,
            correlation_id=correlation_id,
            created_at=now,
            updated_at=now,
        )

    @property
    def is_active(self) -> bool:
        """Вернуть признак активного расписания."""
        return self.status is ScheduleStatus.ACTIVE

    def reschedule(self, schedule: ScheduleSpec, now: datetime, correlation_id: str | None = None) -> None:
        """Заменить правило запуска и вернуть расписание в работу."""
        self.schedule = schedule
        self.status = ScheduleStatus.ACTIVE
        self.next_run_at = None
        if correlation_id is not None:
            self.correlation_id = correlation_id
        self.updated_at = now

    def cancel(self, now: datetime) -> bool:
        """Снять задание с расписания.

        Returns:
            True, если состояние изменилось, иначе False.
        """
        if self.status in (ScheduleStatus.CANCELLED, ScheduleStatus.COMPLETED):
            return False
        self.status = ScheduleStatus.CANCELLED
        self.next_run_at = None
        self.updated_at = now
        return True

    def mark_triggered(self, triggered_at: datetime, next_run_at: datetime | None, now: datetime) -> None:
        """Зафиксировать срабатывание задания.

        Разовое задание становится выполненным, cron-задание остается активным
        и получает следующий плановый запуск.
        """
        self.last_triggered_at = triggered_at
        self.updated_at = now
        if self.schedule.kind is ScheduleKind.ONE_OFF:
            self.status = ScheduleStatus.COMPLETED
            self.next_run_at = None
            return
        self.next_run_at = next_run_at

    def set_next_run(self, next_run_at: datetime | None, now: datetime) -> None:
        """Обновить ближайший плановый запуск активного расписания."""
        if self.status is not ScheduleStatus.ACTIVE:
            return
        self.next_run_at = next_run_at
        self.updated_at = now
