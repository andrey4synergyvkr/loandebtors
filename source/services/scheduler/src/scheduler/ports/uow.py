"""Порт единицы работы с расписаниями и outbox."""

from types import TracebackType
from typing import Protocol, Self

from scheduler.ports.outbox import EventOutbox
from scheduler.ports.repositories import CampaignScheduleRepository, CancelledCampaignRepository


class UnitOfWork(Protocol):
    """Транзакционная граница состояния и исходящих событий.

    Attributes:
        schedules: Репозиторий расписаний.
        cancellations: Репозиторий отметок об отмене кампаний.
        outbox: Запись событий в outbox.
    """

    schedules: CampaignScheduleRepository
    cancellations: CancelledCampaignRepository
    outbox: EventOutbox

    async def __aenter__(self) -> Self:
        """Открыть сессию и транзакцию."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Откатить незавершённую транзакцию и закрыть сессию."""
        ...

    async def commit(self) -> None:
        """Зафиксировать состояние и outbox одной транзакцией."""
        ...


class UnitOfWorkFactory(Protocol):
    """Создаёт новую единицу работы на один сценарий."""

    def __call__(self) -> UnitOfWork:
        """Вернуть новую единицу работы."""
        ...
