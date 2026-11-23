"""Публичные контракты домена Email Channel."""

from email_channel.domain.audit import (
    CHANNEL_ENTITY_TYPE,
    EMAIL_CHANNEL_SERVICE,
    SMTP_ENTITY_ID,
    AuditActor,
    AuditEvent,
)
from email_channel.domain.commands import NotificationCommand, Recipient
from email_channel.domain.config import SmtpConfig, ValidationResult
from email_channel.domain.enums import AuditAction, AuditActorType, AuditOutcome
from email_channel.domain.errors import (
    ChannelNotConfiguredError,
    ConflictError,
    DomainError,
    InvalidStateError,
    NotFoundError,
    SecretError,
    TemplateError,
    ValidationError,
)
from email_channel.domain.events import MessageFailed, MessageSent
from email_channel.domain.ids import (
    AuditEventId,
    CampaignId,
    Channel,
    DebtorId,
    EmailAddress,
    IdempotencyKey,
    MessageId,
    SecretRef,
    TemplateKey,
)
from email_channel.domain.template import EmailTemplate
from email_channel.domain.values import (
    DeliveryOutcome,
    RenderedEmail,
    SendAttempt,
    SendFailure,
    SendReceipt,
    SendResult,
)

__all__ = [
    "CHANNEL_ENTITY_TYPE",
    "EMAIL_CHANNEL_SERVICE",
    "SMTP_ENTITY_ID",
    "AuditAction",
    "AuditActor",
    "AuditActorType",
    "AuditEvent",
    "AuditEventId",
    "AuditOutcome",
    "CampaignId",
    "Channel",
    "ChannelNotConfiguredError",
    "ConflictError",
    "DebtorId",
    "DeliveryOutcome",
    "DomainError",
    "EmailAddress",
    "EmailTemplate",
    "IdempotencyKey",
    "InvalidStateError",
    "MessageFailed",
    "MessageId",
    "MessageSent",
    "NotFoundError",
    "NotificationCommand",
    "Recipient",
    "RenderedEmail",
    "SecretError",
    "SecretRef",
    "SendAttempt",
    "SendFailure",
    "SendReceipt",
    "SendResult",
    "SmtpConfig",
    "TemplateError",
    "TemplateKey",
    "ValidationError",
    "ValidationResult",
]
