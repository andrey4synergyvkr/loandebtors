"""Строковые константы HTTP-адаптера Notifications."""

from typing import Final

API_PREFIX: Final = "/v1"

SYSTEM_TAG: Final = "system"
CAMPAIGNS_TAG: Final = "campaigns"
MESSAGES_TAG: Final = "messages"
TEMPLATES_TAG: Final = "templates"

REQUEST_ID_HEADER: Final = "X-Request-ID"

HEALTH_PATH: Final = "/health"
HEALTH_UNAVAILABLE_DESCRIPTION: Final = "Сервис не готов принимать запросы"

CAMPAIGNS_PATH: Final = API_PREFIX + "/campaigns"
CAMPAIGN_PATH: Final = API_PREFIX + "/campaigns/{campaign_id}"
CAMPAIGN_SCHEDULE_PATH: Final = API_PREFIX + "/campaigns/{campaign_id}/schedule"
CAMPAIGN_START_PATH: Final = API_PREFIX + "/campaigns/{campaign_id}/start"
CAMPAIGN_CANCEL_PATH: Final = API_PREFIX + "/campaigns/{campaign_id}/cancel"
CAMPAIGN_MESSAGES_PATH: Final = API_PREFIX + "/campaigns/{campaign_id}/messages"
CAMPAIGN_MESSAGE_PATH: Final = API_PREFIX + "/campaigns/{campaign_id}/messages/{message_id}"
TEMPLATES_PATH: Final = API_PREFIX + "/templates"
TEMPLATE_PATH: Final = API_PREFIX + "/templates/{template_key}"
TEMPLATE_VERSION_PATH: Final = API_PREFIX + "/templates/{template_key}/versions/{version}"
