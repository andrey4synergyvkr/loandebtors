"""Полная выгрузка выборки должников из АБС."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from notifications.domain import AbsDebtor, Channel, DebtorFilter, ValidationError
from notifications.ports.abs import AbsDebtorSource
from notifications.ports.clock import Clock

logger = logging.getLogger(__name__)

KNOWN_CRITERIA: Final = frozenset({"min_days_overdue", "max_days_overdue", "channel"})


class SelectionError(Exception):
    """Выборка АБС неполна или противоречива."""


@dataclass(frozen=True, slots=True)
class FullSelection:
    """Полная проверенная выборка должников.

    Attributes:
        debtors: Все должники выборки.
        expected_total: Число должников, которое вернула АБС в total.
        fetched_at: Время завершения выгрузки.
    """

    debtors: tuple[AbsDebtor, ...]
    expected_total: int
    fetched_at: datetime


def build_debtor_filter(criteria: Mapping[str, str]) -> DebtorFilter:
    """Отобразить критерии кампании в параметры АБС.

    Raises:
        ValidationError: Известный критерий имеет недопустимое значение.
    """
    for key in criteria:
        if key not in KNOWN_CRITERIA:
            logger.warning(
                "Неизвестный критерий выборки %s игнорируется",
                key,
                extra={"event": "unknown_selection_criterion", "criterion": key},
            )
    min_days = _int_criterion(criteria, "min_days_overdue")
    max_days = _int_criterion(criteria, "max_days_overdue")
    if min_days is not None and max_days is not None and min_days > max_days:
        raise ValidationError("min_days_overdue не может быть больше max_days_overdue")
    channel_value = (criteria.get("channel") or "").strip()
    return DebtorFilter(
        min_days_overdue=min_days,
        max_days_overdue=max_days,
        channel=Channel(channel_value) if channel_value else None,
    )


async def fetch_full_selection(
    source: AbsDebtorSource,
    debtor_filter: DebtorFilter,
    page_size: int,
    max_total: int,
    clock: Clock,
) -> FullSelection:
    """Выгрузить все страницы и проверить полноту выборки.

    Raises:
        SelectionError: Выборка неполна, содержит дубли или превышает лимит.
    """
    debtors: list[AbsDebtor] = []
    seen: set[str] = set()
    expected_total: int | None = None
    page = 1
    while True:
        result = await source.fetch_page(page, page_size, debtor_filter)
        if result.page != page:
            raise SelectionError(f"АБС вернула страницу {result.page} вместо {page}")
        if expected_total is None:
            expected_total = result.total
            if expected_total > max_total:
                raise SelectionError(
                    f"Выборка содержит {expected_total} должников, допустимо не больше {max_total}"
                )
        elif result.total != expected_total:
            raise SelectionError(f"total изменился между страницами: {expected_total} и {result.total}")
        for debtor in result.items:
            if debtor.debtor_id in seen:
                raise SelectionError(f"Дубликат должника {debtor.debtor_id} в выборке")
            seen.add(debtor.debtor_id)
            debtors.append(debtor)
        if not result.has_next:
            break
        if not result.items:
            raise SelectionError("АБС вернула пустую страницу с has_next=true")
        page += 1
    if expected_total is None:
        raise SelectionError("АБС не вернула ни одной страницы")
    if len(debtors) != expected_total:
        raise SelectionError(f"Получено {len(debtors)} должников, АБС ожидала {expected_total}")
    return FullSelection(
        debtors=tuple(debtors),
        expected_total=expected_total,
        fetched_at=clock.now(),
    )


def _int_criterion(criteria: Mapping[str, str], name: str) -> int | None:
    """Разобрать числовой критерий выборки."""
    raw = criteria.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"Критерий {name} должен быть целым числом") from exc
    if value < 0:
        raise ValidationError(f"Критерий {name} не может быть отрицательным")
    return value
