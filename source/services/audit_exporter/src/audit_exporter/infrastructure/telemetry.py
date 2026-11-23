"""Настройка экспорта телеметрии через OpenTelemetry."""

from typing import Final
from uuid import uuid4

from fastapi import FastAPI
from opentelemetry import metrics, propagate, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from sqlalchemy.ext.asyncio import AsyncEngine

from audit_exporter.config import Settings

SERVICE_NAME_ATTRIBUTE: Final = "service.name"
SERVICE_VERSION_ATTRIBUTE: Final = "service.version"
DEPLOYMENT_ENVIRONMENT_ATTRIBUTE: Final = "deployment.environment"
SERVICE_INSTANCE_ID_ATTRIBUTE: Final = "service.instance.id"

OTLP_EXPORT_TIMEOUT_SECONDS: Final = 5.0
SPAN_SCHEDULE_DELAY_MILLISECONDS: Final = 5000
SPAN_MAX_QUEUE_SIZE: Final = 2048
METRIC_EXPORT_TIMEOUT_SECONDS: Final = 5.0
EXCLUDED_URLS: Final = "health"


class TelemetryRuntime:
    """Провайдеры OTel и их корректная остановка."""

    def __init__(
        self,
        tracer_provider: TracerProvider,
        meter_provider: MeterProvider,
        logger_provider: LoggerProvider | None,
    ) -> None:
        """Сохранить созданные провайдеры."""
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._logger_provider = logger_provider

    @property
    def logger_provider(self) -> LoggerProvider | None:
        """Вернуть провайдер логов, если экспорт логов включен."""
        return self._logger_provider

    def instrument_app(self, app: FastAPI, engine: AsyncEngine) -> None:
        """Подключить инструментирование FastAPI, SQLAlchemy и asyncpg."""
        FastAPIInstrumentor.instrument_app(app, excluded_urls=EXCLUDED_URLS)
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        AsyncPGInstrumentor().instrument()  # type: ignore[no-untyped-call]

    def shutdown(self) -> None:
        """Остановить провайдеры и отправить накопленную телеметрию."""
        if self._logger_provider is not None:
            self._logger_provider.shutdown()
        self._tracer_provider.shutdown()
        self._meter_provider.shutdown()


def create_telemetry(settings: Settings, service_version: str) -> TelemetryRuntime | None:
    """Создать провайдеры OTel, если экспорт включен."""
    if not settings.otel_enabled:
        return None

    resource = Resource.create(
        {
            SERVICE_NAME_ATTRIBUTE: settings.service_name,
            SERVICE_VERSION_ATTRIBUTE: service_version,
            DEPLOYMENT_ENVIRONMENT_ATTRIBUTE: settings.environment,
            SERVICE_INSTANCE_ID_ATTRIBUTE: uuid4().hex,
        }
    )

    tracer_provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.otel_sample_ratio)),
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=settings.otlp_endpoint,
                insecure=settings.otel_insecure,
                timeout=OTLP_EXPORT_TIMEOUT_SECONDS,
            ),
            schedule_delay_millis=SPAN_SCHEDULE_DELAY_MILLISECONDS,
            max_queue_size=SPAN_MAX_QUEUE_SIZE,
        )
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=settings.otlp_endpoint,
            insecure=settings.otel_insecure,
            timeout=METRIC_EXPORT_TIMEOUT_SECONDS,
        ),
        export_interval_millis=int(settings.otel_export_interval_seconds * 1000),
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    logger_provider: LoggerProvider | None = None
    if settings.otel_logs_enabled:
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(
                    endpoint=settings.otlp_endpoint,
                    insecure=settings.otel_insecure,
                    timeout=OTLP_EXPORT_TIMEOUT_SECONDS,
                )
            )
        )
        set_logger_provider(logger_provider)

    propagate.set_global_textmap(
        CompositePropagator(
            [
                TraceContextTextMapPropagator(),
                W3CBaggagePropagator(),
            ]
        )
    )
    return TelemetryRuntime(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
    )
