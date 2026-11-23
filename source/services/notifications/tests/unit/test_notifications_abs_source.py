"""Проверка тестового источника АБС и его соответствия контракту."""

from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
import yaml

from notifications.domain import (
    AbsDebtor,
    AbsDebtorPage,
    DebtorContact,
    DebtorFilter,
    DebtSummary,
    Money,
)
from notifications.ports import AbsDebtorSource, AbsTransientError

_REPO_ROOT = Path(__file__).resolve().parents[5]
_CONTRACT_PATH = _REPO_ROOT / "source/contracts/openapi/abs.yaml"


def _contract() -> Any:
    """Загрузить контракт АБС."""
    return yaml.safe_load(_CONTRACT_PATH.read_text(encoding="utf-8"))


def _field_names(model: Any) -> set[str]:
    """Вернуть имена полей dataclass."""
    return {field.name for field in fields(model)}


def test_abs_contract_matches_domain_models() -> None:
    """Схемы контракта АБС совпадают с доменными моделями Notifications."""
    schemas = _contract()["components"]["schemas"]
    assert set(schemas["AbsDebtorPage"]["properties"]) == _field_names(AbsDebtorPage)
    assert set(schemas["AbsDebtor"]["properties"]) == _field_names(AbsDebtor)
    assert set(schemas["DebtorContact"]["properties"]) == _field_names(DebtorContact)
    assert set(schemas["DebtSummary"]["properties"]) == _field_names(DebtSummary)
    assert set(schemas["Money"]["properties"]) == _field_names(Money)


async def test_fake_source_paginates_until_last_page(
    fake_abs_source_factory: Callable[..., AbsDebtorSource],
) -> None:
    """Тестовый источник проходит все страницы и закрывает выборку."""
    source = fake_abs_source_factory()
    page = await source.fetch_page(1, 2, DebtorFilter())

    assert page.page == 1
    assert page.total == 5
    assert len(page.items) == 2
    assert page.has_next is True

    seen = list(page.items)
    while True:
        page = await source.fetch_page(page.page + 1, 2, DebtorFilter())
        seen.extend(page.items)
        if not page.has_next:
            break

    assert page.page == 3
    assert page.has_next is False
    assert len(seen) == 5
    assert len({debtor.debtor_id for debtor in seen}) == 5


async def test_fake_source_reports_unavailable(
    fake_abs_source_factory: Callable[..., AbsDebtorSource],
) -> None:
    """Тестовый источник умеет имитировать недоступность АБС."""
    source = fake_abs_source_factory(failure="unavailable")

    with pytest.raises(AbsTransientError):
        await source.fetch_page(1, 2, DebtorFilter())


async def test_fake_source_reports_incomplete_selection(
    fake_abs_source_factory: Callable[..., AbsDebtorSource],
) -> None:
    """Тестовый источник умеет имитировать неполную выборку."""
    source = fake_abs_source_factory(failure="incomplete")
    page = await source.fetch_page(1, 2, DebtorFilter())

    assert len(page.items) == 1
    assert page.total == 5
    assert page.has_next is False
