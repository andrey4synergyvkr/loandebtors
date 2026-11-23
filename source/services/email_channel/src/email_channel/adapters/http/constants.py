"""Строковые константы HTTP-адаптера Email Channel."""

from typing import Final

API_PREFIX: Final = "/v1"

SYSTEM_TAG: Final = "system"
CHANNEL_TAG: Final = "channel"
TEMPLATES_TAG: Final = "templates"

REQUEST_ID_HEADER: Final = "X-Request-ID"

HEALTH_PATH: Final = "/health"
HEALTH_UNAVAILABLE_DESCRIPTION: Final = "Сервис не готов принимать запросы"

CONFIG_PATH: Final = API_PREFIX + "/config"
CONFIG_VALIDATE_PATH: Final = API_PREFIX + "/config/validate"
TEMPLATES_PATH: Final = API_PREFIX + "/templates"
TEMPLATE_VERSION_PATH: Final = TEMPLATES_PATH + "/{template_key}/versions/{version}"
