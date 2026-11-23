"""Публичные контракты домена Notifications."""

from notifications.domain.audit import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditOutcome,
)
from notifications.domain.campaign import Campaign, DebtorSelection, create_campaign
from notifications.domain.commands import NotificationCommand
from notifications.domain.debtor import (
    AbsDebtor,
    AbsDebtorPage,
    DebtorContact,
    DebtorFilter,
    DebtorSnapshot,
    DebtSummary,
)
from notifications.domain.enums import CampaignStatus, MessageStatus, TemplateStatus
from notifications.domain.errors import (
    ConflictError,
    DomainError,
    InvalidStateError,
    NotFoundError,
    ValidationError,
)
from notifications.domain.events import (
    CampaignCancelled,
    CampaignScheduled,
    CampaignStart,
    MessageFailed,
    MessageSent,
)
from notifications.domain.ids import (
    EMAIL_CHANNEL,
    AuditEventId,
    CampaignId,
    Channel,
    ContractId,
    DebtorId,
    IdempotencyKey,
    MessageId,
    TemplateKey,
)
from notifications.domain.message import MessageAttempt, NotificationMessage
from notifications.domain.template import NotificationTemplate, create_template
from notifications.domain.values import (
    DeliveryOutcome,
    Money,
    Recipient,
    ScheduleKind,
    ScheduleSpec,
)

__all__ = [
    "EMAIL_CHANNEL",
    "AbsDebtor",
    "AbsDebtorPage",
    "AuditAction",
    "AuditActor",
    "AuditActorType",
    "AuditEvent",
    "AuditEventId",
    "AuditOutcome",
    "Campaign",
    "CampaignCancelled",
    "CampaignId",
    "CampaignScheduled",
    "CampaignStart",
    "CampaignStatus",
    "Channel",
    "ConflictError",
    "ContractId",
    "DebtSummary",
    "DebtorContact",
    "DebtorFilter",
    "DebtorId",
    "DebtorSelection",
    "DebtorSnapshot",
    "DeliveryOutcome",
    "DomainError",
    "IdempotencyKey",
    "InvalidStateError",
    "MessageAttempt",
    "MessageFailed",
    "MessageId",
    "MessageSent",
    "MessageStatus",
    "Money",
    "NotFoundError",
    "NotificationCommand",
    "NotificationMessage",
    "NotificationTemplate",
    "Recipient",
    "ScheduleKind",
    "ScheduleSpec",
    "TemplateKey",
    "TemplateStatus",
    "ValidationError",
    "create_campaign",
    "create_template",
]
