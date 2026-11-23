"""Результаты отправки для очереди notification.results."""

from dataclasses import dataclass
from datetime import datetime

from email_channel.domain.ids import CampaignId, Channel, MessageId
from email_channel.domain.values import DeliveryOutcome


@dataclass(frozen=True, slots=True)
class MessageSent:
    """Провайдер принял сообщение.

    Attributes:
        message_id: Сообщение, к которому относится результат.
        campaign_id: Кампания сообщения.
        channel: Канал, принявший сообщение.
        attempt_number: Номер попытки.
        provider_message_id: Идентификатор письма у провайдера.
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
    """Попытка отправки завершилась ошибкой.

    Attributes:
        message_id: Сообщение, к которому относится результат.
        campaign_id: Кампания сообщения.
        channel: Канал, который не смог доставить сообщение.
        attempt_number: Номер попытки.
        outcome: Классификация ошибки.
        retryable: Можно ли повторять попытку.
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
