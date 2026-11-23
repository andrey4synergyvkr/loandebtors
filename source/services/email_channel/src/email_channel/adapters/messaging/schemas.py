"""Схемы входящего сообщения message.send."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from email_channel.domain import (
    CampaignId,
    Channel,
    DebtorId,
    IdempotencyKey,
    MessageId,
    NotificationCommand,
    Recipient,
    TemplateKey,
    ValidationError,
)

CHANNEL_PATTERN = r"^[a-z][a-z0-9_-]*$"
TEMPLATE_KEY_PATTERN = r"^[a-z][a-z0-9._-]*$"


class RecipientPayload(BaseModel):
    """Получатель команды message.send.

    Attributes:
        channel: Канал доставки.
        address: Адрес получателя.
    """

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(pattern=CHANNEL_PATTERN)
    address: str = Field(min_length=1, max_length=320)


class NotificationCommandPayload(BaseModel):
    """Тело команды message.send по контракту AsyncAPI.

    Attributes:
        message_id: Идентификатор сообщения.
        campaign_id: Идентификатор кампании.
        debtor_id: Идентификатор должника.
        channel: Канал доставки.
        template_key: Логический ключ шаблона.
        template_version: Версия шаблона.
        variables: Переменные шаблона.
        recipient: Получатель сообщения.
        idempotency_key: Ключ создания сообщения.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    campaign_id: UUID
    debtor_id: str = Field(min_length=1, max_length=255)
    channel: str = Field(pattern=CHANNEL_PATTERN)
    template_key: str = Field(pattern=TEMPLATE_KEY_PATTERN, max_length=100)
    template_version: int = Field(ge=1)
    variables: dict[str, str]
    recipient: RecipientPayload
    idempotency_key: str = Field(min_length=1, max_length=255)


def to_domain(payload: NotificationCommandPayload) -> NotificationCommand:
    """Преобразовать тело команды в доменную команду."""
    if payload.channel != "email" or payload.recipient.channel != "email":
        raise ValidationError("email.commands принимает только канал email")
    return NotificationCommand(
        message_id=MessageId(payload.message_id),
        campaign_id=CampaignId(payload.campaign_id),
        debtor_id=DebtorId(payload.debtor_id),
        channel=Channel(payload.channel),
        template_key=TemplateKey(payload.template_key),
        template_version=payload.template_version,
        variables=dict(payload.variables),
        recipient=Recipient(
            channel=Channel(payload.recipient.channel),
            address=payload.recipient.address,
        ),
        idempotency_key=IdempotencyKey(payload.idempotency_key),
    )
