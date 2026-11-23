"""Идентификаторы и типы домена Email Channel."""

from typing import NewType
from uuid import UUID

AuditEventId = NewType("AuditEventId", UUID)
CampaignId = NewType("CampaignId", UUID)
MessageId = NewType("MessageId", UUID)
Channel = NewType("Channel", str)
EmailAddress = NewType("EmailAddress", str)
SecretRef = NewType("SecretRef", str)
TemplateKey = NewType("TemplateKey", str)
DebtorId = NewType("DebtorId", str)
IdempotencyKey = NewType("IdempotencyKey", str)
