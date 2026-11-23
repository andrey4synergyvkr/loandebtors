"""Порт управления транзакциями."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol


class TransactionManager(Protocol):
    """Граница транзакции для состояния и outbox."""

    def transaction(self) -> AbstractAsyncContextManager[None]:
        """Открыть транзакцию, в которой фиксируются состояние и outbox."""
        ...
