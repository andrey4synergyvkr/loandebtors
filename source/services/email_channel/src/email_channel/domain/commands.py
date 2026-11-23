"""Входящая команда отправки сообщения."""

from collections.abc import Mapping
from dataclasses import dataclass

from email_channel.domain.ids import (
    CampaignId,
    Channel,
    DebtorId,
    IdempotencyKey,
    MessageId,
    TemplateKey,
)


@dataclass(frozen=True, slots=True)
class Recipient:
    """Получатель сообщения.

    Attributes:
        channel: Канал доставки.
        address: Адрес в формате канала.
    """

    channel: Channel
    address: str


@dataclass(frozen=True, slots=True)
class NotificationCommand:
    """Канально-нейтральная команда message.send.

    Attributes:
        message_id: Идентификатор сообщения и ключ дедупликации.
        campaign_id: Кампания, которой принадлежит сообщение.
        debtor_id: Идентификатор должника из АБС.
        channel: Канал доставки.
        template_key: Логический ключ шаблона.
        template_version: Версия логического шаблона.
        variables: Переменные шаблона.
        recipient: Снимок получателя.
        idempotency_key: Ключ создания сообщения.
    """

    message_id: MessageId
    campaign_id: CampaignId
    debtor_id: DebtorId
    channel: Channel
    template_key: TemplateKey
    template_version: int
    variables: Mapping[str, str]
    recipient: Recipient
    idempotency_key: IdempotencyKey
