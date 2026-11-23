"""Идентификаторы и ключи домена Notifications.

- CampaignId: идентификатор кампании, первичный ключ агрегата Campaign.
- MessageId: идентификатор сообщения и ключ дедупликации при повторной доставке из очереди.
- AuditEventId: идентификатор audit-события, который создает сервис-источник.
- DebtorId: непрозрачный идентификатор должника из АБС.
- ContractId: номер кредитного договора из АБС.
- TemplateKey: логический ключ шаблона без версии.
- Channel: код канала доставки, для v1 используется значение email.
- IdempotencyKey: ключ создания сообщения из кампании, должника и канала.
- EMAIL_CHANNEL: единственный реализованный канал в первой версии.
"""

from typing import Final, NewType
from uuid import UUID

CampaignId = NewType("CampaignId", UUID)
MessageId = NewType("MessageId", UUID)
AuditEventId = NewType("AuditEventId", UUID)
DebtorId = NewType("DebtorId", str)
ContractId = NewType("ContractId", str)
TemplateKey = NewType("TemplateKey", str)
Channel = NewType("Channel", str)
IdempotencyKey = NewType("IdempotencyKey", str)

EMAIL_CHANNEL: Final = Channel("email")
