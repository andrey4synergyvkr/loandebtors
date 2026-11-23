"""Проверка OpenAPI-контракта АБС и данных фикстура."""

import re
from pathlib import Path
from typing import Any

import yaml

from abs.adapters.fixture import JsonDebtorCatalog

_REPO_ROOT = Path(__file__).resolve().parents[5]
_CONTRACT_PATH = _REPO_ROOT / "source/contracts/openapi/abs.yaml"


def _contract() -> Any:
    """Загрузить контракт АБС."""
    return yaml.safe_load(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_has_required_paths() -> None:
    """Контракт описывает health и постраничную выгрузку."""
    contract = _contract()
    assert set(contract["paths"]) == {"/health", "/v1/debtors"}


def test_contract_has_required_parameters() -> None:
    """Контракт фиксирует параметры страницы и критерии выборки."""
    parameters = set(_contract()["components"]["parameters"])
    assert parameters == {
        "Page",
        "PageSize",
        "MinDaysOverdue",
        "MaxDaysOverdue",
        "Channel",
    }


def test_page_schema_fields_match_domain() -> None:
    """Поля AbsDebtorPage совпадают с доменной моделью заглушки."""
    schema = _contract()["components"]["schemas"]["AbsDebtorPage"]
    assert set(schema["properties"]) == {"items", "page", "total", "has_next"}
    assert set(schema["required"]) == {"items", "page", "total", "has_next"}


def test_debtor_schemas_match_domain() -> None:
    """Поля должника, контакта, задолженности и суммы зафиксированы."""
    schemas = _contract()["components"]["schemas"]
    assert set(schemas["AbsDebtor"]["properties"]) == {
        "debtor_id",
        "full_name",
        "contacts",
        "debts",
    }
    assert set(schemas["DebtorContact"]["properties"]) == {
        "channel",
        "address",
        "is_primary",
    }
    assert set(schemas["DebtSummary"]["properties"]) == {
        "contract_id",
        "amount",
        "due_date",
        "days_overdue",
    }
    assert set(schemas["Money"]["properties"]) == {"amount", "currency"}


def test_health_statuses_match_application() -> None:
    """Статусы health соответствуют доменному перечислению."""
    schema = _contract()["components"]["schemas"]["HealthStatus"]
    assert schema["enum"] == ["ok", "degraded", "unavailable"]


def test_fixture_matches_contract_constraints() -> None:
    """Каждый должник фикстура удовлетворяет ограничениям контракта."""
    catalog = JsonDebtorCatalog.from_package()
    for debtor in catalog.debtors:
        assert debtor.debtor_id
        assert debtor.full_name
        assert debtor.contacts
        assert debtor.debts
        for contact in debtor.contacts:
            assert re.fullmatch(r"[a-z][a-z0-9_-]*", contact.channel)
            assert contact.address
        for debt in debtor.debts:
            assert debt.contract_id
            assert re.fullmatch(r"\d+(\.\d{1,2})?", f"{debt.amount:.2f}")
            assert re.fullmatch(r"[A-Z]{3}", debt.currency)
            assert debt.days_overdue >= 0
