"""Сборка снимков должников и сообщений кампании."""

import logging
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from notifications.domain import (
    AbsDebtor,
    Campaign,
    CampaignId,
    Channel,
    DebtorSnapshot,
    IdempotencyKey,
    MessageId,
    MessageStatus,
    NotificationCommand,
    NotificationMessage,
    Recipient,
)

logger = logging.getLogger(__name__)

DEFAULT_CURRENCY: str = "RUB"


def build_snapshots(
    campaign_id: CampaignId,
    debtors: Sequence[AbsDebtor],
    fetched_at: datetime,
) -> list[DebtorSnapshot]:
    """Собрать снимки должников для сохранения в кампании."""
    return [
        DebtorSnapshot(
            campaign_id=campaign_id,
            debtor=debtor,
            fetched_at=fetched_at,
        )
        for debtor in debtors
    ]


def build_messages(
    campaign: Campaign,
    debtors: Sequence[AbsDebtor],
    now: datetime,
    max_attempts: int,
) -> list[NotificationMessage]:
    """Создать сообщения для должников с контактом выбранного канала."""
    messages: list[NotificationMessage] = []
    skipped = 0
    for debtor in debtors:
        recipient = _primary_recipient(debtor, campaign.channel)
        if recipient is None:
            skipped += 1
            continue
        messages.append(
            NotificationMessage(
                id=MessageId(uuid4()),
                campaign_id=campaign.id,
                debtor_id=debtor.debtor_id,
                channel=campaign.channel,
                template_key=campaign.template_key,
                template_version=campaign.template_version,
                variables=_variables(debtor),
                recipient=recipient,
                idempotency_key=IdempotencyKey(f"{campaign.id}:{debtor.debtor_id}:{campaign.channel}"),
                status=MessageStatus.QUEUED,
                attempt_count=0,
                max_attempts=max_attempts,
                created_at=now,
                queued_at=now,
                last_attempt_at=None,
                sent_at=None,
                failed_at=None,
                next_attempt_at=None,
                last_error_code=None,
                last_error_message=None,
            )
        )
    if skipped:
        logger.warning(
            "Должники без контакта канала %s пропущены",
            campaign.channel,
            extra={"event": "messages_skipped", "campaign_id": str(campaign.id), "count": skipped},
        )
    return messages


def build_command(message: NotificationMessage) -> NotificationCommand:
    """Собрать команду message.send из сообщения."""
    return NotificationCommand(
        message_id=message.id,
        campaign_id=message.campaign_id,
        debtor_id=message.debtor_id,
        channel=message.channel,
        template_key=message.template_key,
        template_version=message.template_version,
        variables=dict(message.variables),
        recipient=message.recipient,
        idempotency_key=message.idempotency_key,
    )


def _primary_recipient(debtor: AbsDebtor, channel: Channel) -> Recipient | None:
    """Выбрать основной контакт должника для канала."""
    candidates = [contact for contact in debtor.contacts if contact.channel == channel]
    if not candidates:
        return None
    primary = next((contact for contact in candidates if contact.is_primary), candidates[0])
    return Recipient(channel=channel, address=primary.address)


def _variables(debtor: AbsDebtor) -> dict[str, str]:
    """Собрать переменные рендеринга из данных должника."""
    if not debtor.debts:
        return {
            "debtor_name": debtor.full_name,
            "amount": "0.00",
            "currency": DEFAULT_CURRENCY,
            "days_overdue": "0",
        }
    total = sum((debt.amount.amount for debt in debtor.debts), Decimal("0"))
    currency = debtor.debts[0].amount.currency
    contract = debtor.debts[0]
    days_overdue = max(debt.days_overdue for debt in debtor.debts)
    due_date = min(debt.due_date for debt in debtor.debts)
    return {
        "debtor_name": debtor.full_name,
        "amount": format(total, "f"),
        "currency": currency,
        "contract_id": contract.contract_id,
        "due_date": due_date.isoformat(),
        "days_overdue": str(days_overdue),
    }
