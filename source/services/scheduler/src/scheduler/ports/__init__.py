"""Публичные порты сервиса Scheduler."""

from scheduler.ports.clock import Clock
from scheduler.ports.jobs import JobCallback, JobRegistrar
from scheduler.ports.outbox import (
    EventOutbox,
    OutboxBatchResult,
    OutboxEntry,
    OutboxStore,
    PublishCallback,
)
from scheduler.ports.repositories import CampaignScheduleRepository, CancelledCampaignRepository
from scheduler.ports.uow import UnitOfWork, UnitOfWorkFactory

__all__ = [
    "CampaignScheduleRepository",
    "CancelledCampaignRepository",
    "Clock",
    "EventOutbox",
    "JobCallback",
    "JobRegistrar",
    "OutboxBatchResult",
    "OutboxEntry",
    "OutboxStore",
    "PublishCallback",
    "UnitOfWork",
    "UnitOfWorkFactory",
]
