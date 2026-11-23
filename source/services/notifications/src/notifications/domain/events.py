"""События, публикуемые и потребляемые Notifications."""

from dataclasses import dataclass
from datetime import datetime

from notifications.domain.ids import CampaignId, Channel, MessageId
from notifications.domain.values import DeliveryOutcome, ScheduleSpec


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
    """Отмена запланированной кампании.

    Attributes:
        campaign_id: Кампания, которую нужно снять с расписания.
        occurred_at: Время отмены в UTC.
    """

    campaign_id: CampaignId
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CampaignStart:
    """Команда запуска запланированной кампании.

    Attributes:
        campaign_id: Кампания, которую нужно запустить.
        scheduled_for: Плановое время запуска, для one-off равно run_at.
        occurred_at: Фактическое время публикации события.
    """

    campaign_id: CampaignId
    scheduled_for: datetime
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class MessageSent:
    """Результат успешной отправки сообщения.

    Attributes:
        message_id: Сообщение, к которому относится результат.
        campaign_id: Для обновления состояния кампании.
        channel: Канал, принявший сообщение.
        attempt_number: Номер попытки, первая попытка имеет номер 1.
        provider_message_id: Идентификатор письма провайдера, если вернул.
        occurred_at: Время ответа провайдера.
    """

    message_id: MessageId
    campaign_id: CampaignId
    channel: Channel
    attempt_number: int
    provider_message_id: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class MessageFailed:
    """Результат неуспешной попытки отправки.

    Attributes:
        message_id: Сообщение, к которому относится результат.
        campaign_id: Для обновления состояния кампании.
        channel: Канал, который не смог доставить сообщение.
        attempt_number: Номер попытки, первая попытка имеет номер 1.
        outcome: Классификация ошибки.
        retryable: Можно ли повторять попытку по правилам канала.
        error_code: Код ошибки провайдера.
        error_message: Описание ошибки без персональных данных.
        occurred_at: Время получения ошибки.
    """

    message_id: MessageId
    campaign_id: CampaignId
    channel: Channel
    attempt_number: int
    outcome: DeliveryOutcome
    retryable: bool
    error_code: str | None
    error_message: str | None
    occurred_at: datetime
