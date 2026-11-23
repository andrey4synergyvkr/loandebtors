"""Преобразование данных должника в JSONB и обратно."""

from datetime import date
from decimal import Decimal
from typing import Any

from notifications.domain import Channel, ContractId, DebtorContact, DebtSummary, Money


def contacts_to_json(contacts: tuple[DebtorContact, ...]) -> list[dict[str, Any]]:
    """Записать контакты должника в JSONB."""
    return [
        {
            "channel": contact.channel,
            "address": contact.address,
            "is_primary": contact.is_primary,
        }
        for contact in contacts
    ]


def contacts_from_json(value: list[dict[str, Any]]) -> tuple[DebtorContact, ...]:
    """Прочитать контакты должника из JSONB."""
    return tuple(
        DebtorContact(
            channel=Channel(str(item.get("channel", ""))),
            address=str(item.get("address", "")),
            is_primary=bool(item.get("is_primary", False)),
        )
        for item in value
    )


def debts_to_json(debts: tuple[DebtSummary, ...]) -> list[dict[str, Any]]:
    """Записать задолженности должника в JSONB."""
    return [
        {
            "contract_id": debt.contract_id,
            "amount": format(debt.amount.amount, "f"),
            "currency": debt.amount.currency,
            "due_date": debt.due_date.isoformat(),
            "days_overdue": debt.days_overdue,
        }
        for debt in debts
    ]


def debts_from_json(value: list[dict[str, Any]]) -> tuple[DebtSummary, ...]:
    """Прочитать задолженности должника из JSONB."""
    return tuple(
        DebtSummary(
            contract_id=ContractId(str(item.get("contract_id", ""))),
            amount=Money(
                amount=Decimal(str(item.get("amount", "0"))),
                currency=str(item.get("currency", "RUB")),
            ),
            due_date=date.fromisoformat(str(item.get("due_date", "1970-01-01"))),
            days_overdue=int(item.get("days_overdue", 0)),
        )
        for item in value
    )
