"""Сверка OpenAPI приложения Notifications с контрактом."""

from pathlib import Path
from typing import Any, cast

import yaml

from notifications.config import Settings
from notifications.main import create_app

_REPO_ROOT = Path(__file__).resolve().parents[5]
_OPENAPI_PATH = _REPO_ROOT / "source/contracts/openapi/notifications.yaml"
_HTTP_METHODS = frozenset({"get", "post", "patch", "put", "delete"})


def _contract() -> dict[str, Any]:
    """Загрузить OpenAPI-контракт."""
    return cast(
        dict[str, Any],
        yaml.safe_load(_OPENAPI_PATH.read_text(encoding="utf-8")),
    )


def _application_schema() -> dict[str, Any]:
    """Собрать OpenAPI приложения без инфраструктурных зависимостей."""
    app = create_app(
        Settings(
            service_name="notifications",
            otel_enabled=False,
            check_dependencies=False,
            run_background_workers=False,
        )
    )
    return app.openapi()


def _operations(paths: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Разложить операции по паре путь и HTTP-метод."""
    return {
        (path, method): operation
        for path, methods in paths.items()
        for method, operation in methods.items()
        if method in _HTTP_METHODS
    }


def test_openapi_paths_and_operations_match_contract() -> None:
    """Маршруты и operationId приложения совпадают с контрактом."""
    contract = _operations(_contract()["paths"])
    application = _operations(_application_schema()["paths"])

    assert set(application) == set(contract)
    assert {key: operation.get("operationId") for key, operation in application.items()} == {
        key: operation.get("operationId") for key, operation in contract.items()
    }


def test_openapi_success_codes_match_contract() -> None:
    """Успешные коды ответов приложения совпадают с контрактом."""
    contract = _operations(_contract()["paths"])
    application = _operations(_application_schema()["paths"])

    for key, application_operation in application.items():
        application_codes = set(application_operation["responses"])
        contract_codes = set(contract[key]["responses"])
        assert {code for code in application_codes if code.startswith("2")} == {
            code for code in contract_codes if code.startswith("2")
        }
        assert application_codes <= contract_codes


def test_notifications_contract_has_no_not_implemented_responses() -> None:
    """В контракте не осталось ответов и схемы для нереализованных сценариев."""
    document = _contract()
    responses = document["components"]["responses"]

    assert "NotImplemented" not in responses
    for operation in _operations(document["paths"]).values():
        assert "501" not in operation["responses"]
