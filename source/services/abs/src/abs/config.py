"""Настройки заглушки АБС."""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Параметры окружения заглушки.

    Attributes:
        service_name: Имя сервиса в телеметрии и health.
        environment: Имя среды, например local или production.
        log_level: Уровень логирования.
        otlp_endpoint: Адрес OTLP-коллектора.
        otel_enabled: Включает экспорт телеметрии.
        otel_logs_enabled: Включает экспорт логов по OTLP.
        otel_insecure: Отключает TLS для OTLP, допустимо только локально.
        otel_sample_ratio: Доля сэмплируемых трейсов от 0 до 1.
        otel_export_interval_seconds: Интервал экспорта метрик.
        access_log_health_enabled: Логировать HTTP-запросы health в access-логе.
        http_host: Адрес привязки HTTP-сервера.
        http_port: Порт HTTP-сервера.
        stub_timeout_seconds: Задержка сценария timeout.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    service_name: str = "abs"
    environment: str = "local"
    log_level: str = "INFO"

    otlp_endpoint: str = "http://localhost:4317"
    otel_enabled: bool = False
    otel_logs_enabled: bool = True
    otel_insecure: bool = True
    otel_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_export_interval_seconds: float = Field(default=10.0, gt=0.0)

    access_log_health_enabled: bool = False

    http_host: str = "0.0.0.0"
    http_port: int = 9000

    stub_timeout_seconds: float = Field(
        default=35.0,
        gt=0.0,
        validation_alias=AliasChoices(
            "ABS_STUB_TIMEOUT_SECONDS",
            "STUB_TIMEOUT_SECONDS",
        ),
    )


@lru_cache
def get_settings() -> Settings:
    """Вернуть настройки из переменных окружения и .env."""
    return Settings()
