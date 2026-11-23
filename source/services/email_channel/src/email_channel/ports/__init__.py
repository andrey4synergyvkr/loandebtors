"""Публичные порты Email Channel."""

from email_channel.ports.attempts import SendAttemptRepository
from email_channel.ports.audit import AuditEventOutbox
from email_channel.ports.clock import Clock
from email_channel.ports.config import ChannelConfigRepository
from email_channel.ports.outbox import OutboxBatchResult, OutboxEntry, OutboxStore
from email_channel.ports.probe import SmtpProbe
from email_channel.ports.processed import ProcessedMessageRepository
from email_channel.ports.rate_limit import RateLimiter
from email_channel.ports.renderer import EmailRenderer
from email_channel.ports.results import MessageResultOutbox
from email_channel.ports.sender import EmailSender, SecretsProvider
from email_channel.ports.templates import EmailTemplateRepository
from email_channel.ports.uow import UnitOfWork, UnitOfWorkFactory

__all__ = [
    "AuditEventOutbox",
    "ChannelConfigRepository",
    "Clock",
    "EmailRenderer",
    "EmailSender",
    "EmailTemplateRepository",
    "MessageResultOutbox",
    "OutboxBatchResult",
    "OutboxEntry",
    "OutboxStore",
    "ProcessedMessageRepository",
    "RateLimiter",
    "SecretsProvider",
    "SendAttemptRepository",
    "SmtpProbe",
    "UnitOfWork",
    "UnitOfWorkFactory",
]
