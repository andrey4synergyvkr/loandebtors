"""Интеграционная проверка запуска заглушки АБС."""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import httpx
import pytest

from abs.adapters.http.constants import DEBTORS_PATH, HEALTH_PATH

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[5]
_STARTUP_TIMEOUT_SECONDS = 30.0
_REQUEST_TIMEOUT_SECONDS = 5.0


def _free_port() -> int:
    """Найти свободный TCP-порт на localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(
    base_url: str,
    process: subprocess.Popen[str],
    timeout: float = _STARTUP_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Ждать готовности заглушки и вернуть health-ответ."""
    deadline = time.monotonic() + timeout
    last_error = "нет ответа"

    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout is not None else ""
            pytest.fail(f"Заглушка завершилась до healthcheck: {output}")

        try:
            response = httpx.get(f"{base_url}{HEALTH_PATH}", timeout=_REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 200:
                return cast(dict[str, object], response.json())
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)

        time.sleep(0.2)

    pytest.fail(f"Healthcheck не прошёл за {timeout} секунд: {last_error}")


@pytest.fixture
def abs_url() -> Iterator[str]:
    """Поднять uvicorn заглушки на свободном порту."""
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "OTEL_ENABLED": "false",
            "ENVIRONMENT": "integration",
            "SERVICE_NAME": "abs",
        }
    )
    source_path = str(_REPO_ROOT / "source/services/abs/src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{source_path}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else source_path
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "abs.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        cwd=_REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"

    try:
        _wait_for_health(base_url, process)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_service_starts_and_returns_debtors(abs_url: str) -> None:
    """Заглушка поднимается и отдаёт health и первую страницу должников."""
    health = httpx.get(f"{abs_url}{HEALTH_PATH}", timeout=_REQUEST_TIMEOUT_SECONDS)
    assert health.status_code == 200
    payload = health.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "abs"

    page = httpx.get(
        f"{abs_url}{DEBTORS_PATH}",
        params={"page": 1, "page_size": 5},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    assert page.status_code == 200
    page_payload = page.json()
    assert page_payload["total"] == 24
    assert len(page_payload["items"]) == 5
    assert page_payload["has_next"] is True
