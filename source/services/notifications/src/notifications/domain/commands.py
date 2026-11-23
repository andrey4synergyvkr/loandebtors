"""Команды, публикуемые Notifications в очередь."""

from collections.abc import Mapping
from dataclasses import dataclass

from notifications.domain.ids import (
    CampaignId,
    Channel,
    DebtorId,
    IdempotencyKey,
    MessageId,
    TemplateKey,
)
from notifications.domain.values import Recipient


@dataclass(frozen=True, slots=True)
class NotificationCommand:
    """Канально-нейтральная команда message.send.

    Attributes:
        message_id: Ключ дедупликации в канальном сервисе.
        campaign_id: Связывает команду, кампанию и аудит.
        debtor_id: Нужен для трассировки и аудита без обращения к Notifications.
        channel: Канал, который обрабатывает команду.
        template_key: Логический ключ шаблона.
        template_version: Версия логического шаблона на момент постановки.
        variables: Переменные шаблона, значения приведены к строкам.
        recipient: Снимок контакта на момент создания сообщения.
        idempotency_key: Защита от второго сообщения для той же тройки.
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
