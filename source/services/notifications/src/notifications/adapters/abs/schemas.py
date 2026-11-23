"""Схемы ответа АБС по контракту openapi/abs.yaml."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MoneyPayload(BaseModel):
    """Денежная сумма в ответе АБС.

    Attributes:
        amount: Сумма в основных единицах валюты.
        currency: Код валюты ISO 4217.
    """

    model_config = ConfigDict(extra="forbid")

    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class DebtorContactPayload(BaseModel):
    """Контакт должника в ответе АБС.

    Attributes:
        channel: Канал, к которому относится адрес.
        address: Адрес в формате канала.
        is_primary: Основной контакт для канала.
    """

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    address: str = Field(min_length=1)
    is_primary: bool


class DebtSummaryPayload(BaseModel):
    """Задолженность должника в ответе АБС.

    Attributes:
        contract_id: Номер кредитного договора.
        amount: Сумма к погашению.
        due_date: Плановая дата погашения.
        days_overdue: Количество дней просрочки.
    """

    model_config = ConfigDict(extra="forbid")

    contract_id: str = Field(min_length=1)
    amount: MoneyPayload
    due_date: date
    days_overdue: int = Field(ge=0)


class AbsDebtorPayload(BaseModel):
    """Должник в ответе АБС.

    Attributes:
        debtor_id: Идентификатор должника в АБС.
        full_name: Имя для персонализации.
        contacts: Контакты по каналам.
        debts: Задолженности на момент выгрузки.
    """

    model_config = ConfigDict(extra="forbid")

    debtor_id: str = Field(min_length=1)
    full_name: str = Field(min_length=1)
    contacts: list[DebtorContactPayload]
    debts: list[DebtSummaryPayload] = Field(min_length=1)


class AbsDebtorPagePayload(BaseModel):
    """Одна страница выгрузки АБС.

    Attributes:
        items: Должники текущей страницы.
        page: Номер страницы, первая страница имеет номер 1.
        total: Общее число должников по выборке.
        has_next: Признак наличия следующей страницы.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[AbsDebtorPayload]
    page: int = Field(ge=1)
    total: int = Field(ge=0)
    has_next: bool
