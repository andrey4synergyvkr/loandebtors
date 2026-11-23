"""Composition root заглушки АБС."""

import punq

from abs.adapters.fixture import JsonDebtorCatalog
from abs.config import Settings
from abs.infrastructure.metrics import Metrics


def build_container(settings: Settings) -> punq.Container:
    """Собрать контейнер зависимостей заглушки."""
    container = punq.Container()
    container.register(Settings, instance=settings)
    container.register(Metrics, instance=Metrics())
    container.register(JsonDebtorCatalog, instance=JsonDebtorCatalog.from_package())
    return container
