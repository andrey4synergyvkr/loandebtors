"""Идентификаторы домена Scheduler."""

from typing import NewType
from uuid import UUID

CampaignId = NewType("CampaignId", UUID)
AuditEventId = NewType("AuditEventId", UUID)
