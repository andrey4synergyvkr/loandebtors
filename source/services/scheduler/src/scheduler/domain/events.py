"""События, публикуемые и потребляемые Scheduler."""

from dataclasses import dataclass
from datetime import datetime

from scheduler.domain.ids import CampaignId
from scheduler.domain.values import ScheduleSpec


@dataclass(frozen=True, slots=True)
class CampaignScheduled:
    """Запрос на постановку кампании в расписание.

    Attributes:
        campaign_id: Кампания, которую нужно поставить в расписание.
        schedule: Разовый или cron-запуск.
        occurred_at: Время события в UTC.
    """

    campaign_id: CampaignId
    schedule: ScheduleSpec
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CampaignCancelled:
    """Запрос на снятие кампании с расписания.

    Attributes:
        campaign_id: Кампания, которую нужно снять с расписания.
        occurred_at: Время события в UTC.
    """

    campaign_id: CampaignId
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CampaignStart:
    """Команда запуска запланированной кампании.

    Attributes:
        campaign_id: Кампания, которую нужно запустить.
        scheduled_for: Плановое время запуска, для one_off равно run_at.
        occurred_at: Фактическое время публикации события.
    """

    campaign_id: CampaignId
    scheduled_for: datetime
    occurred_at: datetime
