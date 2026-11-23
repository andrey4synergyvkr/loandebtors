"""Данные должника, полученные из АБС."""

from dataclasses import dataclass
from datetime import date, datetime

from notifications.domain.ids import CampaignId, Channel, ContractId, DebtorId
from notifications.domain.values import Money


@dataclass(frozen=True, slots=True)
class DebtorContact:
    """Контакт должника для канала.

    Attributes:
        channel: Канал, к которому относится адрес.
        address: Адрес в формате канала.
        is_primary: Основной контакт для этого канала.
    """

    channel: Channel
    address: str
    is_primary: bool


@dataclass(frozen=True, slots=True)
class DebtSummary:
    """Снимок задолженности из АБС.

    Attributes:
        contract_id: Номер договора из АБС.
        amount: Сумма к погашению по данным АБС.
        due_date: Плановая дата погашения.
        days_overdue: Количество дней просрочки на момент выгрузки.
    """

    contract_id: ContractId
    amount: Money
    due_date: date
    days_overdue: int


@dataclass(frozen=True, slots=True)
class AbsDebtor:
    """Данные должника из ответа АБС.

    Attributes:
        debtor_id: Идентификатор должника в АБС.
        full_name: Имя для персонализации, в аудит не пишется.
        contacts: Контакты по каналам.
        debts: Задолженности на момент выгрузки.
    """

    debtor_id: DebtorId
    full_name: str
    contacts: tuple[DebtorContact, ...]
    debts: tuple[DebtSummary, ...]


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


@dataclass(frozen=True, slots=True)
class DebtorFilter:
    """Критерии выборки должников для АБС.

    Attributes:
        min_days_overdue: Минимальное число дней просрочки.
        max_days_overdue: Максимальное число дней просрочки.
        channel: Канал, по которому у должника должен быть контакт.
    """

    min_days_overdue: int | None = None
    max_days_overdue: int | None = None
    channel: Channel | None = None


@dataclass(frozen=True, slots=True)
class DebtorSnapshot:
    """Снимок должника, сохраненный для кампании.

    Attributes:
        campaign_id: Кампания, для которой сохранен снимок.
        debtor: Данные должника на момент выгрузки.
        fetched_at: Время получения страницы из АБС.
    """

    campaign_id: CampaignId
    debtor: AbsDebtor
    fetched_at: datetime
