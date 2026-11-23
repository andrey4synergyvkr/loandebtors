"""Строковые константы HTTP-адаптера Audit Exporter."""

from typing import Final

API_PREFIX: Final = "/v1"

SYSTEM_TAG: Final = "system"
AUDIT_TAG: Final = "audit"

REQUEST_ID_HEADER: Final = "X-Request-ID"

HEALTH_PATH: Final = "/health"
HEALTH_UNAVAILABLE_DESCRIPTION: Final = "Сервис не готов принимать запросы"

AUDIT_RECORDS_PATH: Final = API_PREFIX + "/audit-records"
AUDIT_RECORD_PATH: Final = API_PREFIX + "/audit-records/{event_id}"
