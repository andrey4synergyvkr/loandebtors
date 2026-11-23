"""Порт регистрации заданий планировщика."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from scheduler.domain.campaign_schedule import CampaignSchedule
from scheduler.domain.ids import CampaignId
from scheduler.domain.values import ScheduleSpec

type JobCallback = Callable[[CampaignId], Awaitable[None]]


class JobRegistrar(Protocol):
    """Идемпотентная регистрация заданий в планировщике."""

    async def validate(self, schedule: ScheduleSpec) -> None:
        """Проверить, что правило запуска поддерживается планировщиком."""
        ...

    async def register(self, schedule: CampaignSchedule, callback: JobCallback) -> datetime | None:
        """Зарегистрировать задание и вернуть ближайший плановый запуск."""
        ...

    async def remove(self, campaign_id: CampaignId) -> None:
        """Снять задание, если оно существует."""
        ...

    async def next_run_at(self, campaign_id: CampaignId) -> datetime | None:
        """Вернуть ближайший плановый запуск задания."""
        ...
