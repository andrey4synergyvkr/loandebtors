"""Проверка отображения критериев и полноты выборки АБС."""

import logging
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from notifications.application.debtor_selection import (
    SelectionError,
    build_debtor_filter,
    fetch_full_selection,
)
from notifications.domain import (
    EMAIL_CHANNEL,
    AbsDebtor,
    AbsDebtorPage,
    Channel,
    ContractId,
    DebtorContact,
    DebtorFilter,
    DebtorId,
    DebtSummary,
    Money,
    ValidationError,
)
from notifications.infrastructure.clock import SystemClock


def _debtor(debtor_id: str, days_overdue: int = 30) -> AbsDebtor:
    """Создать должника для страницы."""
    return AbsDebtor(
        debtor_id=DebtorId(debtor_id),
        full_name="Тестовый Должник",
        contacts=(
            DebtorContact(
                channel=EMAIL_CHANNEL,
                address="debtor@example.test",
                is_primary=True,
            ),
        ),
        debts=(
            DebtSummary(
                contract_id=ContractId("CR-1"),
                amount=Money(amount=Decimal("1000.00"), currency="RUB"),
                due_date=date(2025, 1, 1),
                days_overdue=days_overdue,
            ),
        ),
    )


class ScriptedSource:
    """Источник страниц с заранее заданным ответом."""

    def __init__(self, pages: Sequence[AbsDebtorPage]) -> None:
        """Сохранить страницы."""
        self._pages = list(pages)
        self.filters: list[DebtorFilter] = []

    async def fetch_page(
        self,
        page: int,
        page_size: int,
        debtor_filter: DebtorFilter,
    ) -> AbsDebtorPage:
        """Вернуть следующую страницу."""
        self.filters.append(debtor_filter)
        return self._pages.pop(0)


def test_build_debtor_filter_maps_known_criteria() -> None:
    """Известные критерии отображаются в параметры АБС."""
    debtor_filter = build_debtor_filter(
        {
            "min_days_overdue": "30",
            "max_days_overdue": "90",
            "channel": "email",
        }
    )

    assert debtor_filter == DebtorFilter(
        min_days_overdue=30,
        max_days_overdue=90,
        channel=Channel("email"),
    )


def test_build_debtor_filter_ignores_unknown_criteria(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Неизвестные критерии игнорируются с предупреждением."""
    with caplog.at_level(logging.WARNING):
        debtor_filter = build_debtor_filter({"region": "moscow"})

    assert debtor_filter == DebtorFilter()
    assert "region" in caplog.text


@pytest.mark.parametrize(
    "criteria",
    [
        {"min_days_overdue": "abc"},
        {"min_days_overdue": "-1"},
        {"min_days_overdue": "90", "max_days_overdue": "30"},
    ],
)
def test_build_debtor_filter_rejects_invalid_values(criteria: dict[str, str]) -> None:
    """Некорректные значения известных критериев отклоняются."""
    with pytest.raises(ValidationError):
        build_debtor_filter(criteria)


async def test_fetch_full_selection_collects_all_pages() -> None:
    """Полная выборка собирает обе страницы и проверяет total."""
    source = ScriptedSource(
        [
            AbsDebtorPage(
                items=(_debtor("A-1"), _debtor("A-2")),
                page=1,
                total=3,
                has_next=True,
            ),
            AbsDebtorPage(
                items=(_debtor("A-3"),),
                page=2,
                total=3,
                has_next=False,
            ),
        ]
    )

    selection = await fetch_full_selection(
        source,
        DebtorFilter(),
        page_size=2,
        max_total=10,
        clock=SystemClock(),
    )

    assert [str(debtor.debtor_id) for debtor in selection.debtors] == ["A-1", "A-2", "A-3"]
    assert selection.expected_total == 3
    assert selection.fetched_at.tzinfo is not None


async def test_fetch_full_selection_rejects_total_change() -> None:
    """total не может меняться между страницами."""
    source = ScriptedSource(
        [
            AbsDebtorPage(items=(_debtor("A-1"),), page=1, total=2, has_next=True),
            AbsDebtorPage(items=(_debtor("A-2"),), page=2, total=3, has_next=False),
        ]
    )

    with pytest.raises(SelectionError):
        await fetch_full_selection(source, DebtorFilter(), 2, 10, SystemClock())


async def test_fetch_full_selection_rejects_duplicates() -> None:
    """Повтор должника между страницами отклоняется."""
    source = ScriptedSource(
        [
            AbsDebtorPage(items=(_debtor("A-1"),), page=1, total=2, has_next=True),
            AbsDebtorPage(items=(_debtor("A-1"),), page=2, total=2, has_next=False),
        ]
    )

    with pytest.raises(SelectionError):
        await fetch_full_selection(source, DebtorFilter(), 1, 10, SystemClock())


async def test_fetch_full_selection_rejects_wrong_page_number() -> None:
    """Номер страницы должен идти по порядку."""
    source = ScriptedSource([AbsDebtorPage(items=(_debtor("A-1"),), page=2, total=1, has_next=False)])

    with pytest.raises(SelectionError):
        await fetch_full_selection(source, DebtorFilter(), 1, 10, SystemClock())


async def test_fetch_full_selection_rejects_incomplete_result() -> None:
    """Число полученных должников должно совпадать с total."""
    source = ScriptedSource([AbsDebtorPage(items=(_debtor("A-1"),), page=1, total=2, has_next=False)])

    with pytest.raises(SelectionError):
        await fetch_full_selection(source, DebtorFilter(), 1, 10, SystemClock())


async def test_fetch_full_selection_rejects_over_limit() -> None:
    """Выборка больше лимита отклоняется до загрузки всех страниц."""
    source = ScriptedSource([AbsDebtorPage(items=(), page=1, total=11, has_next=True)])

    with pytest.raises(SelectionError):
        await fetch_full_selection(source, DebtorFilter(), 10, 10, SystemClock())


async def test_fetch_full_selection_rejects_empty_page_with_next() -> None:
    """Пустая страница с has_next=true противоречит контракту."""
    source = ScriptedSource([AbsDebtorPage(items=(), page=1, total=2, has_next=True)])

    with pytest.raises(SelectionError):
        await fetch_full_selection(source, DebtorFilter(), 1, 10, SystemClock())
