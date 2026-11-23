"""Доменные модели заглушки АБС."""

from abs.domain.debtor import (
    AbsDebtor,
    AbsDebtorPage,
    DebtorContact,
    DebtorFilter,
    DebtSummary,
)

__all__ = [
    "AbsDebtor",
    "AbsDebtorPage",
    "DebtSummary",
    "DebtorContact",
    "DebtorFilter",
]
