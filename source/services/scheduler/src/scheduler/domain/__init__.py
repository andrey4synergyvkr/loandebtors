"""Публичные контракты домена Scheduler."""

from scheduler.domain.audit import (
    AuditAction,
    AuditActor,
    AuditActorType,
    AuditEvent,
    AuditOutcome,
)
from scheduler.domain.campaign_schedule import CampaignSchedule
from scheduler.domain.enums import ScheduleStatus
from scheduler.domain.errors import (
    DomainError,
    InvalidStateError,
    NotFoundError,
    ValidationError,
)
from scheduler.domain.events import CampaignCancelled, CampaignScheduled, CampaignStart
from scheduler.domain.ids import AuditEventId, CampaignId
from scheduler.domain.values import ScheduleKind, ScheduleSpec

__all__ = [
    "AuditAction",
    "AuditActor",
    "AuditActorType",
    "AuditEvent",
    "AuditEventId",
    "AuditOutcome",
    "CampaignCancelled",
    "CampaignId",
    "CampaignSchedule",
    "CampaignScheduled",
    "CampaignStart",
    "DomainError",
    "InvalidStateError",
    "NotFoundError",
    "ScheduleKind",
    "ScheduleSpec",
    "ScheduleStatus",
    "ValidationError",
]
