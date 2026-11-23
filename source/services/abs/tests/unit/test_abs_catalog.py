"""Проверка каталога должников из JSON-фикстура."""

import pytest

from abs.adapters.fixture import FixtureError, JsonDebtorCatalog
from abs.domain import DebtorFilter


@pytest.fixture(scope="module")
def catalog() -> JsonDebtorCatalog:
    """Загрузить каталог из фикстура пакета."""
    return JsonDebtorCatalog.from_package()


def test_fixture_contains_unique_sorted_debtors(catalog: JsonDebtorCatalog) -> None:
    """Фикстур содержит 24 должника с уникальными отсортированными идентификаторами."""
    identifiers = [debtor.debtor_id for debtor in catalog.debtors]
    assert len(identifiers) == 24
    assert identifiers == sorted(identifiers)
    assert len(identifiers) == len(set(identifiers))


def test_first_page_reports_next_page(catalog: JsonDebtorCatalog) -> None:
    """Первая страница содержит пять должников и признак следующей страницы."""
    page = catalog.fetch_page(1, 5, DebtorFilter())
    assert page.page == 1
    assert len(page.items) == 5
    assert page.total == 24
    assert page.has_next is True


def test_last_page_closes_selection(catalog: JsonDebtorCatalog) -> None:
    """Последняя страница содержит остаток выборки без следующей страницы."""
    page = catalog.fetch_page(5, 5, DebtorFilter())
    assert page.page == 5
    assert len(page.items) == 4
    assert page.total == 24
    assert page.has_next is False


def test_page_beyond_selection_is_empty(catalog: JsonDebtorCatalog) -> None:
    """Страница за пределами выборки возвращает пустой список должников."""
    page = catalog.fetch_page(10, 5, DebtorFilter())
    assert page.items == ()
    assert page.total == 24
    assert page.has_next is False


def test_min_days_overdue_filter(catalog: JsonDebtorCatalog) -> None:
    """Фильтр минимальной просрочки оставляет только подходящих должников."""
    page = catalog.fetch_page(1, 100, DebtorFilter(min_days_overdue=100))
    assert page.total == 16
    assert all(any(debt.days_overdue >= 100 for debt in debtor.debts) for debtor in page.items)


def test_range_filter_uses_any_debt(catalog: JsonDebtorCatalog) -> None:
    """Диапазон просрочки проверяется хотя бы по одной задолженности."""
    page = catalog.fetch_page(1, 100, DebtorFilter(min_days_overdue=380, max_days_overdue=400))
    identifiers = {debtor.debtor_id for debtor in page.items}
    assert "ABS-100010" in identifiers
    assert page.total >= 1


def test_channel_filter(catalog: JsonDebtorCatalog) -> None:
    """Фильтр канала оставляет должников с контактом этого канала."""
    page = catalog.fetch_page(1, 100, DebtorFilter(channel="sms"))
    assert page.total == 2
    assert {debtor.debtor_id for debtor in page.items} == {"ABS-100023", "ABS-100024"}


def test_invalid_page_is_rejected(catalog: JsonDebtorCatalog) -> None:
    """Номер страницы меньше единицы отклоняется."""
    with pytest.raises(ValueError):
        catalog.fetch_page(0, 5, DebtorFilter())


def test_empty_fixture_is_rejected() -> None:
    """Пустой набор должников не создаёт каталог."""
    with pytest.raises(FixtureError):
        JsonDebtorCatalog(())
