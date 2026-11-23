"""Каталог должников из JSON-фикстура."""

import json
from datetime import date
from decimal import Decimal
from importlib import resources
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from abs.domain import AbsDebtor, AbsDebtorPage, DebtorContact, DebtorFilter, DebtSummary

FIXTURE_PACKAGE: Final = "abs.data"
FIXTURE_NAME: Final = "debtors.json"


class FixtureError(ValueError):
    """Фикстур не соответствует ожидаемой форме."""


class _ContactModel(BaseModel):
    """Контакт должника в фикстуре."""

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_-]*$")
    address: str = Field(min_length=1)
    is_primary: bool


class _DebtModel(BaseModel):
    """Задолженность должника в фикстуре."""

    model_config = ConfigDict(extra="forbid")

    contract_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    due_date: date
    days_overdue: int = Field(ge=0)


class _DebtorModel(BaseModel):
    """Должник в фикстуре."""

    model_config = ConfigDict(extra="forbid")

    debtor_id: str = Field(min_length=1)
    full_name: str = Field(min_length=1)
    contacts: list[_ContactModel]
    debts: list[_DebtModel] = Field(min_length=1)


class _FixtureModel(BaseModel):
    """Корень фикстура."""

    model_config = ConfigDict(extra="forbid")

    debtors: list[_DebtorModel] = Field(min_length=1)


class JsonDebtorCatalog:
    """Каталог, который загружает должников из JSON-фикстура."""

    def __init__(self, debtors: tuple[AbsDebtor, ...]) -> None:
        """Сохранить проверенный набор должников."""
        if not debtors:
            raise FixtureError("Фикстур не содержит должников")
        identifiers = [debtor.debtor_id for debtor in debtors]
        if len(identifiers) != len(set(identifiers)):
            raise FixtureError("Идентификаторы должников повторяются")
        self._debtors = tuple(sorted(debtors, key=lambda debtor: debtor.debtor_id))

    @classmethod
    def from_package(cls) -> "JsonDebtorCatalog":
        """Загрузить фикстур из пакета."""
        fixture = resources.files(FIXTURE_PACKAGE).joinpath(FIXTURE_NAME)
        text = fixture.read_text(encoding="utf-8")
        return cls(_parse_debtors(text))

    @property
    def debtors(self) -> tuple[AbsDebtor, ...]:
        """Вернуть всех должников фикстура."""
        return self._debtors

    def fetch_page(
        self,
        page: int,
        page_size: int,
        debtor_filter: DebtorFilter,
    ) -> AbsDebtorPage:
        """Вернуть страницу выборки по критериям."""
        if page < 1:
            raise ValueError("Номер страницы должен быть не меньше 1")
        if page_size < 1:
            raise ValueError("Размер страницы должен быть не меньше 1")

        selected = tuple(debtor for debtor in self._debtors if _matches(debtor, debtor_filter))
        total = len(selected)
        start = (page - 1) * page_size
        end = start + page_size
        items = selected[start:end] if start < total else ()
        return AbsDebtorPage(
            items=items,
            page=page,
            total=total,
            has_next=end < total,
        )


def _parse_debtors(text: str) -> tuple[AbsDebtor, ...]:
    """Разобрать JSON-фикстур и вернуть должников."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FixtureError(f"Фикстур не является корректным JSON: {exc}") from exc
    try:
        fixture = _FixtureModel.model_validate(payload)
    except ValidationError as exc:
        raise FixtureError(f"Фикстур не прошёл проверку: {exc}") from exc
    return tuple(_to_domain(debtor) for debtor in fixture.debtors)


def _to_domain(debtor: _DebtorModel) -> AbsDebtor:
    """Преобразовать модель фикстура в доменного должника."""
    return AbsDebtor(
        debtor_id=debtor.debtor_id,
        full_name=debtor.full_name,
        contacts=tuple(
            DebtorContact(
                channel=contact.channel,
                address=contact.address,
                is_primary=contact.is_primary,
            )
            for contact in debtor.contacts
        ),
        debts=tuple(
            DebtSummary(
                contract_id=debt.contract_id,
                amount=debt.amount,
                currency=debt.currency,
                due_date=debt.due_date,
                days_overdue=debt.days_overdue,
            )
            for debt in debtor.debts
        ),
    )


def _matches(debtor: AbsDebtor, debtor_filter: DebtorFilter) -> bool:
    """Проверить, попадает ли должник в выборку."""
    days_filter_enabled = (
        debtor_filter.min_days_overdue is not None or debtor_filter.max_days_overdue is not None
    )
    if days_filter_enabled and not any(
        _days_match(debt.days_overdue, debtor_filter) for debt in debtor.debts
    ):
        return False
    if debtor_filter.channel is None:
        return True
    return any(contact.channel == debtor_filter.channel for contact in debtor.contacts)


def _days_match(days_overdue: int, debtor_filter: DebtorFilter) -> bool:
    """Проверить, попадает ли срок просрочки в диапазон."""
    if debtor_filter.min_days_overdue is not None and days_overdue < debtor_filter.min_days_overdue:
        return False
    return not (debtor_filter.max_days_overdue is not None and days_overdue > debtor_filter.max_days_overdue)
