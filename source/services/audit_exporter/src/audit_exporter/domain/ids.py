"""Идентификаторы журнала аудита.

- AuditEventId: идентификатор события, который создаёт сервис-источник.
- CampaignId: идентификатор кампании.
- MessageId: идентификатор сообщения.
- Channel: код канала доставки.
"""

from typing import NewType
from uuid import UUID

AuditEventId = NewType("AuditEventId", UUID)
CampaignId = NewType("CampaignId", UUID)
MessageId = NewType("MessageId", UUID)
Channel = NewType("Channel", str)
