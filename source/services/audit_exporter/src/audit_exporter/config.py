"""Настройки сервиса Audit Exporter."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Параметры окружения сервиса.

    Attributes:
        service_name: Имя сервиса в телеметрии и health.
        environment: Имя среды, например local или production.
        log_level: Уровень логирования.
        database_url: DSN PostgreSQL с async-драйвером.
        database_echo: Выводить SQL-запросы в лог.
        database_pool_size: Базовый размер пула соединений.
        database_max_overflow: Допустимое превышение размера пула.
        rabbitmq_url: AMQP DSN RabbitMQ.
        rabbitmq_connection_timeout: Таймаут установки соединения.
        rabbitmq_prefetch_count: Размер prefetch для консьюмера.
        rabbitmq_retry_ttl_seconds: TTL retry-очередей.
        rabbitmq_retry_max_attempts: Предел повторных обработок сообщения.
        otlp_endpoint: Адрес OTLP-коллектора.
        otel_enabled: Включает экспорт телеметрии.
        otel_logs_enabled: Включает экспорт логов по OTLP.
        otel_insecure: Отключает TLS для OTLP, допустимо только локально.
        otel_sample_ratio: Доля сэмплируемых трейсов от 0 до 1.
        otel_export_interval_seconds: Интервал экспорта метрик.
        access_log_health_enabled: Логировать HTTP-запросы health в access-логе.
        http_host: Адрес привязки HTTP-сервера.
        http_port: Порт HTTP-сервера.
        health_check_timeout_seconds: Таймаут одной health-проверки.
        run_background_workers: Запускать консьюмер audit.events.
        check_dependencies: Проверять PostgreSQL и RabbitMQ в health.
        audit_consumer_reconnect_seconds: Пауза перед повторным подключением консьюмера.
        queue_metrics_poll_interval_seconds: Интервал сбора глубины очередей.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "audit_exporter"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://loandebtors:loandebtors@localhost:5432/loandebtors"
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 5

    rabbitmq_url: str = "amqp://loandebtors:loandebtors@localhost:5672/"
    rabbitmq_connection_timeout: float = 10.0
    rabbitmq_prefetch_count: int = Field(default=50, ge=1)
    rabbitmq_retry_ttl_seconds: float = 60.0
    rabbitmq_retry_max_attempts: int = Field(default=10, ge=1)

    otlp_endpoint: str = "http://localhost:4317"
    otel_enabled: bool = False
    otel_logs_enabled: bool = True
    otel_insecure: bool = True
    otel_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_export_interval_seconds: float = Field(default=10.0, gt=0.0)

    access_log_health_enabled: bool = False

    http_host: str = "0.0.0.0"
    http_port: int = 8004

    health_check_timeout_seconds: float = Field(default=3.0, gt=0.0)
    run_background_workers: bool = True
    check_dependencies: bool = True
    audit_consumer_reconnect_seconds: float = Field(default=5.0, gt=0.0)
    queue_metrics_poll_interval_seconds: float = Field(default=10.0, gt=0.0)


@lru_cache
def get_settings() -> Settings:
    """Вернуть настройки из переменных окружения и .env."""
    return Settings()
