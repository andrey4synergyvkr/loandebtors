"""Доменные модели заглушки АБС."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DebtorContact:
    """Контакт должника для канала.

    Attributes:
        channel: Канал, к которому относится адрес.
        address: Адрес в формате канала.
        is_primary: Основной контакт для этого канала.
    """

    channel: str
    address: str
    is_primary: bool


@dataclass(frozen=True, slots=True)
class DebtSummary:
    """Снимок задолженности должника.

    Attributes:
        contract_id: Номер кредитного договора.
        amount: Сумма к погашению.
        currency: Код валюты ISO 4217.
        due_date: Плановая дата погашения.
        days_overdue: Количество дней просрочки на момент выгрузки.
    """

    contract_id: str
    amount: Decimal
    currency: str
    due_date: date
    days_overdue: int


@dataclass(frozen=True, slots=True)
class AbsDebtor:
    """Должник в выборке АБС.

    Attributes:
        debtor_id: Идентификатор должника в АБС.
        full_name: Имя для персонализации, в аудит не пишется.
        contacts: Контакты по каналам.
        debts: Задолженности на момент выгрузки.
    """

    debtor_id: str
    full_name: str
    contacts: tuple[DebtorContact, ...]
    debts: tuple[DebtSummary, ...]


@dataclass(frozen=True, slots=True)
class DebtorFilter:
    """Критерии выборки должников.

    Attributes:
        min_days_overdue: Минимальное число дней просрочки.
        max_days_overdue: Максимальное число дней просрочки.
        channel: Канал, по которому у должника должен быть контакт.
    """

    min_days_overdue: int | None = None
    max_days_overdue: int | None = None
    channel: str | None = None


@dataclass(frozen=True, slots=True)
class AbsDebtorPage:
    """Одна страница выгрузки АБС.

    Attributes:
        items: Должники текущей страницы.
        page: Номер страницы, первая страница имеет номер 1.
        total: Общее число должников по выборке.
        has_next: Признак наличия следующей страницы.
    """

    items: tuple[AbsDebtor, ...]
    page: int
    total: int
    has_next: bool
