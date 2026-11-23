"""Строковые константы HTTP-адаптера Scheduler."""

from typing import Final

SYSTEM_TAG: Final = "system"

REQUEST_ID_HEADER: Final = "X-Request-ID"

HEALTH_PATH: Final = "/health"
HEALTH_UNAVAILABLE_DESCRIPTION: Final = "Сервис не готов принимать запросы"
