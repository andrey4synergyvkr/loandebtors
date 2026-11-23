# Audit Exporter

Сервис Audit Exporter: приём `audit.event` из RabbitMQ, append-only журнал в схеме
`audit` и read-only API выгрузки для администратора. Реализованы инфраструктура,
приём событий, чтение журнала и меры надёжности: обнаружение конфликтов,
метрики очередей, переподключение consumer и redrive DLQ.

## Что реализовано

- настройки сервиса, PostgreSQL через SQLAlchemy и Alembic;
- схема `audit` и таблица `audit_record` с индексами и trigger append-only;
- consumer очереди `audit.events` с manual ack, retry и DLQ;
- идемпотентность по `event_id`, повторная доставка не создаёт дубль;
- конфликт: тот же `event_id` с другим содержимым уходит в DLQ с причиной `conflict`;
- supervisor consumer переподключается к RabbitMQ после сбоя;
- метрики глубины очередей `audit.events`, retry и DLQ, состояния consumer;
- health с проверками `application`, `database`, `rabbitmq`, `audit_consumer`;
- read-only API `/v1/audit-records` и `/v1/audit-records/{event_id}`;
- фильтры по кампании, каналу, действию и времени, курсор по `sequence`;
- self-audit: первая страница выгрузки и чтение по `event_id` фиксируются
  событием `audit.exported`;
- Problem+JSON для ошибок API: 404, 422 и 500; неизвестный маршрут и
  неподдерживаемый метод отдают стандартный JSON FastAPI;
- провайдеры OpenTelemetry, OTLP gRPC, JSON-логи и метрики;
- скрипт redrive DLQ с проверкой публикации;
- модульные, BDD и интеграционные тесты.

## Требования

- Python 3.12;
- `uv`;
- Docker и Docker Compose для инфраструктуры и контейнерного запуска.

## Переменные окружения

Настройки читаются из переменных окружения и файла `.env` в корне репозитория.

| Переменная                          | Значение по умолчанию                                              |
|-------------------------------------|--------------------------------------------------------------------|
| `SERVICE_NAME`                      | `audit_exporter`                                                   |
| `ENVIRONMENT`                       | `local`                                                            |
| `LOG_LEVEL`                         | `INFO`                                                             |
| `DATABASE_URL`                      | `postgresql+asyncpg://loandebtors:loandebtors@localhost:5432/loandebtors` |
| `DATABASE_ECHO`                     | `false`                                                            |
| `DATABASE_POOL_SIZE`                | `5`                                                                |
| `DATABASE_MAX_OVERFLOW`             | `5`                                                                |
| `RABBITMQ_URL`                      | `amqp://loandebtors:loandebtors@localhost:5672/`                   |
| `RABBITMQ_CONNECTION_TIMEOUT`       | `10`                                                               |
| `RABBITMQ_PREFETCH_COUNT`           | `50`                                                               |
| `RABBITMQ_RETRY_TTL_SECONDS`        | `60`                                                               |
| `RABBITMQ_RETRY_MAX_ATTEMPTS`       | `10`                                                               |
| `HTTP_HOST`                         | `0.0.0.0`                                                          |
| `HTTP_PORT`                         | `8004`                                                             |
| `OTLP_ENDPOINT`                     | `http://localhost:4317`                                            |
| `OTEL_ENABLED`                      | `false`                                                            |
| `OTEL_LOGS_ENABLED`                 | `true`                                                             |
| `OTEL_INSECURE`                     | `true`                                                             |
| `OTEL_SAMPLE_RATIO`                 | `1.0`                                                              |
| `OTEL_EXPORT_INTERVAL_SECONDS`      | `10`                                                               |
| `ACCESS_LOG_HEALTH_ENABLED`         | `false`                                                            |
| `HEALTH_CHECK_TIMEOUT_SECONDS`      | `3`                                                                |
| `RUN_BACKGROUND_WORKERS`            | `true`                                                             |
| `CHECK_DEPENDENCIES`                | `true`                                                             |
| `AUDIT_CONSUMER_RECONNECT_SECONDS`  | `5`                                                                |
| `QUEUE_METRICS_POLL_INTERVAL_SECONDS` | `10`                                                             |

`CHECK_DEPENDENCIES=false` и `RUN_BACKGROUND_WORKERS=false` используются в
юнит-тестах: сервис не подключается к PostgreSQL и RabbitMQ, health проверяет
только приложение.

## Локальный запуск

Все команды выполняются из корня репозитория.

```bash
make install
make env
make up
make migrate-audit-exporter
make run-audit-exporter
```

`make up` поднимает PostgreSQL, RabbitMQ, Mailpit, OTel Collector, Tempo,
Prometheus, Grafana и Loki. `make migrate-audit-exporter` создаёт схему `audit`
и таблицу `audit_record`. `make run-audit-exporter` запускает uvicorn на порту
8004.

Без Makefile:

```bash
uv sync --all-packages
uv run alembic -c source/services/audit_exporter/alembic.ini upgrade head
uv run uvicorn audit_exporter.main:app --reload --host 0.0.0.0 --port 8004
```

## Проверка

Health:

```bash
curl -i http://localhost:8004/health
```

Пример ответа:

```json
{
  "status": "ok",
  "service": "audit_exporter",
  "version": "0.1.0",
  "uptime_seconds": 12.4,
  "checks": [
    {
      "name": "application",
      "status": "ok",
      "detail": "Сервис готов принимать запросы"
    },
    {
      "name": "database",
      "status": "ok",
      "detail": "PostgreSQL доступен"
    },
    {
      "name": "rabbitmq",
      "status": "ok",
      "detail": "Соединение с RabbitMQ установлено"
    },
    {
      "name": "audit_consumer",
      "status": "ok",
      "detail": "Консьюмер audit.events принимает сообщения"
    }
  ]
}
```

Если PostgreSQL или RabbitMQ недоступны, health возвращает 503. Ошибка
supervisor консьюмера переводит статус в `degraded`, HTTP-код остаётся 200.

Выгрузка журнала:

```bash
curl "http://localhost:8004/v1/audit-records?limit=10"
curl "http://localhost:8004/v1/audit-records?campaign_id=<uuid>&action=message.sent"
curl "http://localhost:8004/v1/audit-records/<event_id>"
```

Ответ страницы:

```json
{
  "items": [
    {
      "sequence": 1,
      "event": {
        "event_id": "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d",
        "occurred_at": "2026-11-22T12:00:00Z",
        "service": "notifications",
        "actor": {"type": "system", "identifier": "notifications"},
        "action": "message.sent",
        "entity_type": "message",
        "entity_id": "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d",
        "campaign_id": "5a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
        "message_id": "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d",
        "channel": "email",
        "outcome": "success",
        "details": {"provider": "mailpit"},
        "correlation_id": "corr-1",
        "trace_id": null
      },
      "ingested_at": "2026-11-22T12:00:01Z"
    }
  ],
  "next_cursor": null
}
```

Ошибки возвращаются с `content-type: application/problem+json`:

```json
{
  "type": "urn:loandebtors:error:validation",
  "title": "Unprocessable Entity",
  "status": 422,
  "detail": "query.limit: Input should be greater than or equal to 1",
  "instance": "/v1/audit-records",
  "code": "validation_error"
}
```

Swagger и сгенерированная схема:

- `http://localhost:8004/docs`
- `http://localhost:8004/openapi.json`

Источник истины для HTTP API: [audit-exporter.yaml](../../contracts/openapi/audit-exporter.yaml).
Контракты RabbitMQ: [loandebtors.yaml](../../contracts/asyncapi/loandebtors.yaml).

## Обмен сообщениями

Audit Exporter работает с topic exchange `loan-debtors.events`.

| Направление | Очередь             | Routing key        |
|-------------|---------------------|--------------------|
| Входящие    | `audit.events`      | `audit.event`      |
| Исходящие   | `audit.events.dlq`  | `audit.events.dlq` |

Для очереди объявлены durable-очередь, retry-очередь с TTL и DLQ. Публикация
выполняется с publisher confirms и `mandatory=True`. Consumer работает с manual
ack и prefetch.

Ошибка валидации сообщения публикуется в DLQ и подтверждается. Ошибка БД
возвращает сообщение в retry-очередь. После `RABBITMQ_RETRY_MAX_ATTEMPTS`
сообщение уходит в DLQ. Повторная доставка не создаёт дубль благодаря
уникальному `event_id`.

Пример публикации события:

```bash
uv run python - <<'PY'
import asyncio
import json
import aio_pika

async def main() -> None:
    connection = await aio_pika.connect_robust(
        "amqp://loandebtors:loandebtors@localhost:5672/"
    )
    async with connection:
        channel = await connection.channel()
        exchange = await channel.get_exchange("loan-debtors.events")
        payload = {
            "event_id": "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d",
            "occurred_at": "2026-11-22T12:00:00Z",
            "service": "notifications",
            "actor": {"type": "system", "identifier": "notifications"},
            "action": "message.sent",
            "entity_type": "message",
            "entity_id": "3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d",
            "campaign_id": None,
            "message_id": None,
            "channel": "email",
            "outcome": "success",
            "details": {"provider": "mailpit"},
            "correlation_id": "corr-1",
            "trace_id": None,
        }
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
                headers={"correlation_id": "corr-1"},
            ),
            routing_key="audit.event",
        )

asyncio.run(main())
PY
```

## Мониторинг

При `OTEL_ENABLED=true` сервис экспортирует трейсы, метрики и логи по OTLP gRPC
в коллектор. На стенде Collector передаёт трейсы в Tempo, отдаёт метрики для
Prometheus, отправляет логи в Loki, а Grafana показывает все три вида данных.

- Collector: `http://localhost:4317`
- Grafana: `http://localhost:3000`, по умолчанию `admin` / `admin`
- Prometheus: `http://localhost:9090`
- Loki: `http://localhost:3100`
- Tempo: `http://localhost:3200`

В Grafana открывайте дашборд `LoanDebtors Audit Exporter: Overview`.
Базовые запросы к Prometheus:

```promql
target_info{job="audit_exporter"}
sum(rate(loandebtors_audit_exporter_audit_ingested_total[5m]))
sum(rate(loandebtors_audit_exporter_audit_conflicts_total[5m]))
sum(rate(loandebtors_audit_exporter_http_requests_total[5m]))
loandebtors_audit_exporter_queue_messages{job="audit_exporter"}
loandebtors_audit_exporter_consumer_running{job="audit_exporter"}
```

Трейсы ищите в Explore с источником Tempo по сервису `audit_exporter`.
Доступность коллектора не влияет на health сервиса: телеметрия работает в
режиме best effort.

## Логи

Сервис пишет структурированные JSON-логи в stdout и одновременно отправляет их
по OTLP в Collector, который передаёт записи в Loki. Поля: `timestamp`, `level`,
`logger`, `message`, `service`, `service_version`, `environment`,
`correlation_id`, `trace_id`, `span_id`, `event`, `event_id`, `action`,
`source_service`, HTTP-поля access-лога и `exception` при ошибке.

Примеры LogQL:

```logql
{service_name="audit_exporter"}
```

```logql
{service_name="audit_exporter"} | json | level="ERROR"
```

Логи в Docker остаются доступны для локальной отладки:

```bash
docker compose -f source/infra/compose.yaml logs -f audit-exporter
```

Экспорт логов отключается `OTEL_LOGS_ENABLED=false`. Access-логи health по
умолчанию не пишутся; включить их можно `ACCESS_LOG_HEALTH_ENABLED=true`.

## Тесты и проверки

Только Audit Exporter:

```bash
uv run pytest source/services/audit_exporter/tests -q
```

Отдельные наборы:

```bash
uv run pytest source/services/audit_exporter/tests/unit -q
uv run pytest source/services/audit_exporter/tests/bdd -q
```

Интеграционный тест поднимает PostgreSQL и RabbitMQ через Testcontainers,
применяет миграции, запускает uvicorn и проверяет приём, чтение, фильтры,
курсор, `audit.exported`, DLQ и append-only:

```bash
uv run pytest -m integration source/services/audit_exporter/tests/integration -q
```

Линтер, типы и быстрые тесты:

```bash
make check
```

Все тесты, включая интеграционные:

```bash
make test-all
```

Сквозные сценарии на полном стенде:

```bash
make up-all
make e2e
```

## Запуск в Docker

Только Audit Exporter с зависимостями:

```bash
docker compose -f source/infra/compose.yaml up -d --build audit-exporter
curl http://localhost:8004/health
docker compose -f source/infra/compose.yaml logs -f audit-exporter
```

Полный стенд из корня репозитория:

```bash
docker compose up -d --build
```

Остановка:

```bash
make down
```

## Структура

```
src/audit_exporter/
├── domain/                 AuditEvent, AuditRecord, фильтры и ошибки
├── application/            health, AuditIngestService, AuditReader
├── ports/                  AuditStore и Clock
├── adapters/http/          health, read-only журнал, Problem и middleware
├── adapters/messaging/     RabbitMQ, топология, consumer и DLQ-публикатор
├── adapters/persistence/   PostgreSQL, модель audit_record, курсор и репозиторий
└── infrastructure/         логирование, корреляция, метрики, трассировка и телеметрия
```

## Разбор DLQ

Сообщения, которые не удалось обработать, попадают в `audit.events.dlq`. Перед
повторной публикацией посмотрите их:

```bash
uv run python source/services/audit_exporter/scripts/redrive_dlq.py --limit 10 --dry-run
```

Повторная публикация в `audit.events`:

```bash
make redrive-audit-dlq LIMIT=10
```

Скрипт `source/services/audit_exporter/scripts/redrive_dlq.py` подтверждает
исходное сообщение только после успешной публикации. При ошибке публикации
сообщение возвращается в DLQ.

## Ограничения

- журнал append-only: изменение, удаление и очистка запрещены trigger БД;
- retention не реализован, журнал растёт без ограничений;
- аутентификация и авторизация не выполняются по OC-2;
- сервис рассчитан на один экземпляр в учебном стенде.

Архитектурное описание: [5-building-block-view.md](../../../docs/arc42/5-building-block-view.md).
Телеметрия: [8-cross-cutting-concepts.md](../../../docs/arc42/8-cross-cutting-concepts.md), раздел 8.4.
