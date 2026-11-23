.DEFAULT_GOAL := help
SHELL := /bin/sh

UV ?= uv
COMPOSE ?= docker compose -f source/infra/compose.yaml
ASYNCAPI ?= asyncapi
OPENAPI_VALIDATOR ?= uvx openapi-spec-validator

NOTIFICATIONS_PORT ?= 8001
SCHEDULER_PORT ?= 8002
EMAIL_CHANNEL_PORT ?= 8003
AUDIT_EXPORTER_PORT ?= 8004
ABS_PORT ?= 9000
LIMIT ?= 100

.PHONY: help install env lock format lint typecheck test test-unit test-bdd test-integration test-all e2e e2e-down contracts check \
        up up-all down ps logs build migrate migrate-notifications migrate-scheduler \
        migrate-email-channel migrate-audit-exporter run-notifications run-scheduler \
        run-email-channel run-audit-exporter run-abs smoke smoke-scheduler smoke-email-channel smoke-audit-exporter smoke-abs \
        redrive-audit-dlq clean

help: ## Показать список команд
	@awk 'BEGIN {FS = ":.*## "; printf "Usage:\n  make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-26s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Создать окружение и установить зависимости
	$(UV) sync --all-packages

env: ## Создать .env из .env.example
	@test -f .env && echo ".env already exists" || (cp .env.example .env && echo "Created .env from .env.example")

lock: ## Обновить uv.lock
	$(UV) lock

format: ## Отформатировать код
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

lint: ## Проверить стиль и форматирование
	$(UV) run ruff format --check .
	$(UV) run ruff check .

typecheck: ## Проверить типы
	$(UV) run mypy source/services

test: ## Запустить быстрые тесты без интеграционных
	$(UV) run pytest

test-unit: ## Только модульные тесты
	$(UV) run pytest -m "not integration"

test-bdd: ## Только BDD-сценарии
	$(UV) run pytest -m bdd

test-integration: ## Интеграционные тесты с запуском сервиса
	$(UV) run pytest -m integration

test-all: ## Запустить все тесты, включая интеграционные
	$(UV) run pytest -m ""

e2e: ## Сквозные тесты на поднятом стенде
	$(UV) run pytest -o addopts="" -m e2e source/acceptance -q

e2e-down: ## Остановить стенд после e2e
	$(COMPOSE) down

check: lint typecheck test ## lint + typecheck + test

contracts: ## Проверить OpenAPI и AsyncAPI контракты
	$(ASYNCAPI) validate source/contracts/asyncapi/loandebtors.yaml
	@for spec in source/contracts/openapi/*.yaml; do \
		echo "checking $$spec"; \
		$(OPENAPI_VALIDATOR) "$$spec"; \
	done

up: ## Поднять инфраструктуру, мониторинг и заглушку АБС
	$(COMPOSE) up -d postgres rabbitmq mailpit otel-collector loki tempo prometheus grafana abs

up-all: ## Поднять инфраструктуру и сервисы
	$(COMPOSE) up -d --build

down: ## Остановить контейнеры
	$(COMPOSE) down

ps: ## Показать контейнеры
	$(COMPOSE) ps

logs: ## Смотреть логи контейнеров
	$(COMPOSE) logs -f

build: ## Собрать образы сервисов
	$(COMPOSE) build

migrate: migrate-notifications migrate-scheduler migrate-email-channel migrate-audit-exporter ## Применить миграции всех сервисов

migrate-notifications: ## Миграции Notifications
	$(UV) run alembic -c source/services/notifications/alembic.ini upgrade head

migrate-scheduler: ## Миграции Scheduler
	$(UV) run alembic -c source/services/scheduler/alembic.ini upgrade head

migrate-email-channel: ## Миграции Email Channel
	$(UV) run alembic -c source/services/email_channel/alembic.ini upgrade head

migrate-audit-exporter: ## Миграции Audit Exporter
	$(UV) run alembic -c source/services/audit_exporter/alembic.ini upgrade head

run-notifications: ## Запустить Notifications
	$(UV) run uvicorn notifications.main:app --reload --host 0.0.0.0 --port $(NOTIFICATIONS_PORT)

run-scheduler: ## Запустить Scheduler
	$(UV) run uvicorn scheduler.main:app --reload --host 0.0.0.0 --port $(SCHEDULER_PORT)

run-email-channel: ## Запустить Email Channel
	$(UV) run uvicorn email_channel.main:app --reload --host 0.0.0.0 --port $(EMAIL_CHANNEL_PORT)

run-audit-exporter: ## Запустить Audit Exporter
	$(UV) run uvicorn audit_exporter.main:app --reload --host 0.0.0.0 --port $(AUDIT_EXPORTER_PORT)

run-abs: ## Запустить заглушку АБС
	$(UV) run uvicorn abs.main:app --reload --host 0.0.0.0 --port $(ABS_PORT)

smoke: ## Проверить health Notifications
	$(UV) run python -c "import json, urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://localhost:$(NOTIFICATIONS_PORT)/health')), ensure_ascii=False, indent=2))"

smoke-scheduler: ## Проверить health Scheduler
	$(UV) run python -c "import json, urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://localhost:$(SCHEDULER_PORT)/health')), ensure_ascii=False, indent=2))"

smoke-email-channel: ## Проверить health Email Channel
	$(UV) run python -c "import json, urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://localhost:$(EMAIL_CHANNEL_PORT)/health')), ensure_ascii=False, indent=2))"

smoke-audit-exporter: ## Проверить health Audit Exporter
	$(UV) run python -c "import json, urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://localhost:$(AUDIT_EXPORTER_PORT)/health')), ensure_ascii=False, indent=2))"

redrive-audit-dlq: ## Повторно опубликовать сообщения из audit.events.dlq
	$(UV) run python source/services/audit_exporter/scripts/redrive_dlq.py --limit $(LIMIT)

smoke-abs: ## Проверить health заглушки АБС
	$(UV) run python -c "import json, urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://localhost:$(ABS_PORT)/health')), ensure_ascii=False, indent=2))"

clean: ## Удалить кеши и временные файлы
	find . -path ./.venv -prune -o -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
