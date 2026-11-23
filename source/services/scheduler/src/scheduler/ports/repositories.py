"""Порты репозиториев Scheduler."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from scheduler.domain.campaign_schedule import CampaignSchedule
from scheduler.domain.ids import CampaignId


class CampaignScheduleRepository(Protocol):
    """Доступ к расписаниям кампаний в текущей транзакции."""

    async def get(self, campaign_id: CampaignId) -> CampaignSchedule | None:
        """Вернуть расписание кампании или None."""
        ...

    async def save(self, schedule: CampaignSchedule) -> None:
        """Создать или обновить расписание."""
        ...

    async def list_active(self) -> Sequence[CampaignSchedule]:
        """Вернуть активные расписания для восстановления заданий."""
        ...


class CancelledCampaignRepository(Protocol):
    """Хранит отметки об отмене кампаний.

    Отметка переживает команды, пришедшие в другом порядке. Если отмена
    обработана раньше регистрации расписания, последующая регистрация увидит
    отметку и не создаст задание.
    """

    async def add(self, campaign_id: CampaignId, occurred_at: datetime) -> None:
        """Идемпотентно сохранить время отмены кампании."""
        ...

    async def get_occurred_at(self, campaign_id: CampaignId) -> datetime | None:
        """Вернуть время отмены кампании или None, если отмены не было."""
        ...
