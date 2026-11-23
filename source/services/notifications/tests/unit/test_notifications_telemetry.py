"""Проверка настроек телеметрии."""

from notifications.config import Settings
from notifications.infrastructure.telemetry import create_telemetry


def test_telemetry_is_disabled_by_default() -> None:
    """При выключенном экспорте провайдеры не создаются."""
    settings = Settings(otel_enabled=False)

    runtime = create_telemetry(settings, "0.1.0")

    assert runtime is None
