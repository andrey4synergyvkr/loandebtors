"""Порт выгрузки данных АБС."""

from typing import Protocol

from notifications.domain import AbsDebtorPage, DebtorFilter


class AbsSourceError(Exception):
    """Базовая ошибка обращения к АБС."""


class AbsTransientError(AbsSourceError):
    """Временная ошибка АБС: сеть, таймаут или 5xx."""


class AbsPermanentError(AbsSourceError):
    """Постоянная ошибка АБС: 4xx или нарушение контракта ответа."""


class AbsDebtorSource(Protocol):
    """Постраничная выгрузка должников из АБС."""

    async def fetch_page(
        self,
        page: int,
        page_size: int,
        debtor_filter: DebtorFilter,
    ) -> AbsDebtorPage:
        """Вернуть одну страницу выгрузки, первая страница имеет номер 1.

        Raises:
            AbsTransientError: АБС временно недоступна.
            AbsPermanentError: Запрос отклонен или ответ не соответствует контракту.
        """
        ...
