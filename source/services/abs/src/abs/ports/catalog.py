"""Порт каталога должников."""

from typing import Protocol

from abs.domain import AbsDebtorPage, DebtorFilter


class DebtorCatalog(Protocol):
    """Источник страниц должников."""

    def fetch_page(
        self,
        page: int,
        page_size: int,
        debtor_filter: DebtorFilter,
    ) -> AbsDebtorPage:
        """Вернуть одну страницу выборки, первая страница имеет номер 1."""
        ...
