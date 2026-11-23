"""Публичные порты Notifications."""

from notifications.ports.abs import (
    AbsDebtorSource,
    AbsPermanentError,
    AbsSourceError,
    AbsTransientError,
)
from notifications.ports.audit import AuditEventOutbox
from notifications.ports.clock import Clock
from notifications.ports.maintenance import ExhaustedMessageCommand, MaintenanceStore
from notifications.ports.messaging import (
    CampaignScheduledPublisher,
    NotificationCommandPublisher,
)
from notifications.ports.outbox import (
    CampaignEventOutbox,
    MessageCommandOutbox,
    OutboxBatchResult,
    OutboxEntry,
    OutboxStore,
)
from notifications.ports.repositories import (
    CampaignRepository,
    DebtorSnapshotRepository,
    MessageAttemptRepository,
    NotificationMessageRepository,
    NotificationTemplateRepository,
)
from notifications.ports.transactions import TransactionManager
from notifications.ports.uow import UnitOfWork, UnitOfWorkFactory

__all__ = [
    "AbsDebtorSource",
    "AbsPermanentError",
    "AbsSourceError",
    "AbsTransientError",
    "AuditEventOutbox",
    "CampaignEventOutbox",
    "CampaignRepository",
    "CampaignScheduledPublisher",
    "Clock",
    "DebtorSnapshotRepository",
    "ExhaustedMessageCommand",
    "MaintenanceStore",
    "MessageAttemptRepository",
    "MessageCommandOutbox",
    "NotificationCommandPublisher",
    "NotificationMessageRepository",
    "NotificationTemplateRepository",
    "OutboxBatchResult",
    "OutboxEntry",
    "OutboxStore",
    "TransactionManager",
    "UnitOfWork",
    "UnitOfWorkFactory",
]
