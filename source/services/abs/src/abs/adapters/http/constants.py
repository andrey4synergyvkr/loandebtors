"""Строковые константы HTTP-адаптера заглушки АБС."""

from typing import Final

API_PREFIX: Final = "/v1"

SYSTEM_TAG: Final = "system"
DEBTORS_TAG: Final = "debtors"

REQUEST_ID_HEADER: Final = "X-Request-ID"
STUB_SCENARIO_HEADER: Final = "X-Stub-Scenario"

HEALTH_PATH: Final = "/health"
HEALTH_UNAVAILABLE_DESCRIPTION: Final = "Сервис не готов принимать запросы"
DEBTORS_PATH: Final = API_PREFIX + "/debtors"

DEFAULT_PAGE: Final = 1
DEFAULT_PAGE_SIZE: Final = 500
MIN_PAGE_SIZE: Final = 1
MAX_PAGE_SIZE: Final = 1000

CHANNEL_PATTERN: Final = r"^[a-z][a-z0-9_-]*$"

SCENARIO_OK: Final = "ok"
SCENARIO_ERROR_500: Final = "error_500"
SCENARIO_UNAVAILABLE: Final = "unavailable"
SCENARIO_TIMEOUT: Final = "timeout"
SCENARIO_INCOMPLETE: Final = "incomplete"
SCENARIO_VALUES: Final[frozenset[str]] = frozenset(
    {
        SCENARIO_OK,
        SCENARIO_ERROR_500,
        SCENARIO_UNAVAILABLE,
        SCENARIO_TIMEOUT,
        SCENARIO_INCOMPLETE,
    }
)
