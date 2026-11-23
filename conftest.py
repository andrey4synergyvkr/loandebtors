"""Общие настройки pytest для монорепозитория."""

import os
from collections.abc import Generator
from typing import Any

import pytest

INTEGRATION_REQUIRED_ENV = "INTEGRATION_REQUIRED"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[Any],
) -> Generator[None, Any, None]:
    """Запретить пропуск интеграционных тестов в обязательном режиме."""
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    if (
        os.environ.get(INTEGRATION_REQUIRED_ENV) == "1"
        and report.skipped
        and item.get_closest_marker("integration") is not None
    ):
        report.outcome = "failed"
        report.longrepr = (
            f"Интеграционный тест пропущен, а {INTEGRATION_REQUIRED_ENV}=1 требует его выполнения"
        )
