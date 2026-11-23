"""HTTP-адаптер выгрузки должников из АБС."""

import asyncio
import logging
from typing import Any

import httpx

from notifications.adapters.abs.schemas import AbsDebtorPagePayload, AbsDebtorPayload
from notifications.config import Settings
from notifications.domain import (
    AbsDebtor,
    AbsDebtorPage,
    Channel,
    ContractId,
    DebtorContact,
    DebtorFilter,
    DebtorId,
    DebtSummary,
    Money,
)
from notifications.ports.abs import AbsPermanentError, AbsTransientError

logger = logging.getLogger(__name__)

DEBTORS_PATH: str = "/v1/debtors"


class HttpAbsDebtorSource:
    """Запрашивает страницы выборки у АБС по OpenAPI-контракту."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Сохранить настройки и при необходимости создать HTTP-клиент."""
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.abs_base_url,
            timeout=settings.abs_timeout_seconds,
        )
        self._owns_client = client is None

    async def fetch_page(
        self,
        page: int,
        page_size: int,
        debtor_filter: DebtorFilter,
    ) -> AbsDebtorPage:
        """Вернуть страницу выборки с ограниченным повтором временных ошибок."""
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if debtor_filter.min_days_overdue is not None:
            params["min_days_overdue"] = debtor_filter.min_days_overdue
        if debtor_filter.max_days_overdue is not None:
            params["max_days_overdue"] = debtor_filter.max_days_overdue
        if debtor_filter.channel is not None:
            params["channel"] = debtor_filter.channel

        last_error: Exception | None = None
        for attempt in range(1, self._settings.abs_max_attempts + 1):
            try:
                response = await self._client.get(DEBTORS_PATH, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < self._settings.abs_max_attempts:
                    await asyncio.sleep(self._settings.abs_retry_base_seconds * attempt)
                    continue
                raise AbsTransientError(f"АБС недоступна: {type(exc).__name__}") from exc

            if response.status_code >= 500:
                last_error = AbsTransientError(f"АБС вернула HTTP {response.status_code}")
                if attempt < self._settings.abs_max_attempts:
                    await asyncio.sleep(self._settings.abs_retry_base_seconds * attempt)
                    continue
                raise last_error

            if response.status_code >= 400:
                raise AbsPermanentError(f"АБС отклонила запрос: HTTP {response.status_code}")

            try:
                payload = AbsDebtorPagePayload.model_validate(response.json())
            except ValueError as exc:
                raise AbsPermanentError(f"Ответ АБС не соответствует контракту: {exc}") from exc
            return _to_domain(payload)

        raise AbsTransientError(f"АБС недоступна: {last_error}")

    async def aclose(self) -> None:
        """Закрыть HTTP-клиент, созданный адаптером."""
        if self._owns_client:
            await self._client.aclose()


def _to_domain(payload: AbsDebtorPagePayload) -> AbsDebtorPage:
    """Преобразовать ответ АБС в доменную страницу."""
    return AbsDebtorPage(
        items=tuple(_debtor_to_domain(debtor) for debtor in payload.items),
        page=payload.page,
        total=payload.total,
        has_next=payload.has_next,
    )


def _debtor_to_domain(payload: AbsDebtorPayload) -> AbsDebtor:
    """Преобразовать должника из ответа АБС."""
    return AbsDebtor(
        debtor_id=DebtorId(payload.debtor_id),
        full_name=payload.full_name,
        contacts=tuple(
            DebtorContact(
                channel=Channel(contact.channel),
                address=contact.address,
                is_primary=contact.is_primary,
            )
            for contact in payload.contacts
        ),
        debts=tuple(
            DebtSummary(
                contract_id=ContractId(debt.contract_id),
                amount=Money(amount=debt.amount.amount, currency=debt.amount.currency),
                due_date=debt.due_date,
                days_overdue=debt.days_overdue,
            )
            for debt in payload.debts
        ),
    )
