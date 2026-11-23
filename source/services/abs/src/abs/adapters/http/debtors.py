"""Постраничная выгрузка должников из заглушки АБС."""

import asyncio
import logging
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from abs.adapters.fixture import JsonDebtorCatalog
from abs.adapters.http.constants import (
    CHANNEL_PATTERN,
    DEBTORS_PATH,
    DEBTORS_TAG,
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MIN_PAGE_SIZE,
    SCENARIO_ERROR_500,
    SCENARIO_INCOMPLETE,
    SCENARIO_OK,
    SCENARIO_TIMEOUT,
    SCENARIO_UNAVAILABLE,
    SCENARIO_VALUES,
    STUB_SCENARIO_HEADER,
)
from abs.adapters.http.problems import (
    PROBLEM_MEDIA_TYPE,
    Problem,
    ProblemResponse,
    internal_error,
    invalid_scenario,
    problem_response,
    unavailable,
)
from abs.config import Settings
from abs.domain import AbsDebtorPage, DebtorFilter

logger = logging.getLogger(__name__)

router = APIRouter(tags=[DEBTORS_TAG])


class MoneyResponse(BaseModel):
    """Денежная сумма в ответе АБС.

    Attributes:
        amount: Сумма в основных единицах валюты.
        currency: Код валюты ISO 4217.
    """

    model_config = ConfigDict(extra="forbid")

    amount: str = Field(pattern=r"^\d+(\.\d{1,2})?$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class DebtorContactResponse(BaseModel):
    """Контакт должника в ответе АБС.

    Attributes:
        channel: Канал, к которому относится адрес.
        address: Адрес в формате канала.
        is_primary: Основной контакт для этого канала.
    """

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(pattern=CHANNEL_PATTERN)
    address: str = Field(min_length=1)
    is_primary: bool


class DebtSummaryResponse(BaseModel):
    """Снимок задолженности в ответе АБС.

    Attributes:
        contract_id: Номер кредитного договора.
        amount: Сумма к погашению.
        due_date: Плановая дата погашения.
        days_overdue: Количество дней просрочки.
    """

    model_config = ConfigDict(extra="forbid")

    contract_id: str
    amount: MoneyResponse
    due_date: date
    days_overdue: int


class AbsDebtorResponse(BaseModel):
    """Должник в ответе АБС.

    Attributes:
        debtor_id: Идентификатор должника в АБС.
        full_name: Имя для персонализации.
        contacts: Контакты по каналам.
        debts: Задолженности на момент выгрузки.
    """

    model_config = ConfigDict(extra="forbid")

    debtor_id: str
    full_name: str
    contacts: list[DebtorContactResponse]
    debts: list[DebtSummaryResponse]


class AbsDebtorPageResponse(BaseModel):
    """Одна страница выгрузки АБС.

    Attributes:
        items: Должники текущей страницы.
        page: Номер страницы, первая страница имеет номер 1.
        total: Общее число должников по выборке.
        has_next: Признак наличия следующей страницы.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[AbsDebtorResponse]
    page: int = Field(ge=1)
    total: int = Field(ge=0)
    has_next: bool


def _problem_response(description: str) -> dict[str, Any]:
    """Описать ответ Problem с media type application/problem+json."""
    return {
        "description": description,
        "content": {
            PROBLEM_MEDIA_TYPE: {
                "schema": Problem.model_json_schema(),
            }
        },
    }


@router.get(
    DEBTORS_PATH,
    response_model=AbsDebtorPageResponse,
    operation_id="listDebtors",
    responses={
        400: _problem_response("Некорректный запрос или неизвестный сценарий заглушки"),
        422: _problem_response("Некорректные параметры запроса"),
        500: _problem_response("Внутренняя ошибка АБС"),
        503: _problem_response("АБС недоступна"),
    },
)
async def list_debtors(
    request: Request,
    page: int = Query(DEFAULT_PAGE, ge=1, description="Номер страницы, начиная с 1"),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE,
        ge=MIN_PAGE_SIZE,
        le=MAX_PAGE_SIZE,
        description="Размер страницы выгрузки",
    ),
    min_days_overdue: int | None = Query(
        None,
        ge=0,
        description="Минимальное число дней просрочки",
    ),
    max_days_overdue: int | None = Query(
        None,
        ge=0,
        description="Максимальное число дней просрочки",
    ),
    channel: str | None = Query(
        None,
        pattern=CHANNEL_PATTERN,
        description="Канал, по которому у должника должен быть контакт",
    ),
    scenario: str | None = Header(None, alias=STUB_SCENARIO_HEADER),
) -> AbsDebtorPageResponse | ProblemResponse:
    """Вернуть страницу выборки или смоделированную ошибку."""
    scenario_value = scenario or SCENARIO_OK
    if scenario_value not in SCENARIO_VALUES:
        return problem_response(invalid_scenario(f"Неизвестный сценарий: {scenario_value}"))

    settings: Settings = request.app.state.settings
    catalog: JsonDebtorCatalog = request.app.state.catalog

    if scenario_value == SCENARIO_UNAVAILABLE:
        return problem_response(unavailable("Заглушка имитирует недоступность АБС"))
    if scenario_value == SCENARIO_ERROR_500:
        return problem_response(internal_error("Заглушка имитирует внутреннюю ошибку АБС"))
    if scenario_value == SCENARIO_TIMEOUT:
        await asyncio.sleep(settings.stub_timeout_seconds)

    result = catalog.fetch_page(
        page=page,
        page_size=page_size,
        debtor_filter=DebtorFilter(
            min_days_overdue=min_days_overdue,
            max_days_overdue=max_days_overdue,
            channel=channel,
        ),
    )
    if scenario_value == SCENARIO_INCOMPLETE:
        result = _truncate(result)

    logger.info(
        "Страница выгрузки должников",
        extra={
            "event": "debtors_page",
            "page": page,
            "page_size": page_size,
            "debtor_count": len(result.items),
            "scenario": scenario_value,
        },
    )
    return _to_response(result)


def _truncate(page: AbsDebtorPage) -> AbsDebtorPage:
    """Усечь страницу для сценария incomplete."""
    if not page.items:
        return page
    return AbsDebtorPage(
        items=page.items[:-1],
        page=page.page,
        total=page.total,
        has_next=False,
    )


def _to_response(page: AbsDebtorPage) -> AbsDebtorPageResponse:
    """Преобразовать доменную страницу в ответ HTTP-адаптера."""
    return AbsDebtorPageResponse(
        items=[
            AbsDebtorResponse(
                debtor_id=debtor.debtor_id,
                full_name=debtor.full_name,
                contacts=[
                    DebtorContactResponse(
                        channel=contact.channel,
                        address=contact.address,
                        is_primary=contact.is_primary,
                    )
                    for contact in debtor.contacts
                ],
                debts=[
                    DebtSummaryResponse(
                        contract_id=debt.contract_id,
                        amount=MoneyResponse(
                            amount=_format_amount(debt.amount),
                            currency=debt.currency,
                        ),
                        due_date=debt.due_date,
                        days_overdue=debt.days_overdue,
                    )
                    for debt in debtor.debts
                ],
            )
            for debtor in page.items
        ],
        page=page.page,
        total=page.total,
        has_next=page.has_next,
    )


def _format_amount(value: Decimal) -> str:
    """Отформатировать сумму с двумя знаками после запятой."""
    return format(value.quantize(Decimal("0.01")), "f")
