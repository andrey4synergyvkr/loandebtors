# Scheduler

Сервис Scheduler: планирование запуска кампаний по расписанию. Принимает
`campaign.scheduled` и `campaign.cancelled`, хранит расписания в PostgreSQL,
регистрирует задания APScheduler, публикует `campaign.start` и пишет audit-события.

## Что реализовано

- доменная модель `CampaignSchedule`, `ScheduleSpec` и переходы состояний;
- consumer очереди `scheduler.commands` с manual ack, prefetch, retry и DLQ;
- автоматическое восстановление подписки consumer после переподключения RabbitMQ;
- задания APScheduler на MemoryJobStore с misfire grace и coalesce для one_off и
  cron-расписаний;
- восстановление активных расписаний после перезапуска через `list_active`;
- единый outbox для `campaign.start` и `audit.event` в схеме `scheduler`;
- репозиторий расписаний и транзакционная единица работы;
- идемпотентная отмена с отметкой в таблице `cancelled_campaign`, которая
  защищает от порядка `campaign.cancelled` раньше `campaign.scheduled`;
- публикация `campaign.start` в `notification.commands` через publisher confirms;
- audit-события `campaign.scheduled`, `campaign.started`, `campaign.cancelled`;
- health с проверками `application`, `database`, `rabbitmq`, `scheduler`,
  `consumer`, `outbox_relay`;
- OTel traces/metrics/logs, JSON-логи с `trace_id` и `span_id`;
- unit, BDD и интеграционные тесты, включая сквозной сценарий RabbitMQ.

## Как работает

1. Notifications публикует `campaign.scheduled` в `scheduler.commands`.
2. Consumer проверяет сообщение, сохраняет расписание и audit-событие в одной
   транзакции, затем регистрирует задание APScheduler.
3. В назначенное время задание публикует `campaign.start` в
   `notification.commands` и audit-событие `campaign.started`.
4. Outbox relay публикует накопленные события в exchange `loan-debtors.events`.
5. `campaign.cancelled` сохраняет отметку об отмене, снимает задание и переводит
   расписание в `cancelled`. Если отмена пришла раньше расписания, регистрация
   задания увидит отметку и не создаст его.
6. При старте сервис регистрирует заново все активные расписания из БД.

Публикация запуска выполняется через транзакционный outbox: запись
`campaign.start` фиксируется вместе с изменением расписания. Гарантия доставки
at-least-once, повторная доставка возможна.

## Требования

- Python 3.12;
- `uv`;
- Docker и Docker Compose для инфраструктуры, мониторинга и контейнерного запуска.

## Переменные окружения

Настройки читаются из переменных окружения и файла `.env` в корне репозитория.

| Переменная                       | Значение по умолчанию                                                    |
|----------------------------------|--------------------------------------------------------------------------|
| `SERVICE_NAME`                   | `scheduler`                                                              |
| `ENVIRONMENT`                    | `local`                                                                  |
| `LOG_LEVEL`                      | `INFO`                                                                   |
| `DATABASE_URL`                   | `postgresql+asyncpg://loandebtors:loandebtors@localhost:5432/loandebtors` |
| `DATABASE_ECHO`                  | `false`                                                                  |
| `DATABASE_POOL_SIZE`             | `5`                                                                      |
| `DATABASE_MAX_OVERFLOW`          | `5`                                                                      |
| `RABBITMQ_URL`                   | `amqp://loandebtors:loandebtors@localhost:5672/`                         |
| `RABBITMQ_CONNECTION_TIMEOUT`    | `10`                                                                     |
| `RABBITMQ_PREFETCH_COUNT`        | `50`                                                                     |
| `RABBITMQ_RETRY_TTL_SECONDS`     | `60`                                                                     |
| `RABBITMQ_RETRY_MAX_ATTEMPTS`    | `10`                                                                     |
| `HTTP_HOST`                      | `0.0.0.0`                                                                |
| `HTTP_PORT`                      | `8002`                                                                   |
| `OTLP_ENDPOINT`                  | `http://localhost:4317`                                                  |
| `OTEL_ENABLED`                   | `false`                                                                  |
| `OTEL_LOGS_ENABLED`              | `true`                                                                   |
| `OTEL_INSECURE`                  | `true`                                                                   |
| `OTEL_SAMPLE_RATIO`              | `1.0`                                                                    |
| `OTEL_EXPORT_INTERVAL_SECONDS`   | `10`                                                                     |
| `ACCESS_LOG_HEALTH_ENABLED`      | `false`                                                                  |
| `CHECK_DEPENDENCIES`             | `true`                                                                   |
| `RUN_BACKGROUND_WORKERS`         | `true`                                                                   |
| `HEALTH_CHECK_TIMEOUT_SECONDS`   | `5`                                                                      |
| `OUTBOX_POLL_INTERVAL_SECONDS`   | `1`                                                                      |
| `OUTBOX_BATCH_SIZE`              | `100`                                                                    |
| `OUTBOX_MAX_ATTEMPTS`            | `10`                                                                     |
| `OUTBOX_RETRY_BASE_SECONDS`      | `1`                                                                      |
| `OUTBOX_RETRY_MAX_SECONDS`       | `60`                                                                     |
| `OUTBOX_HEALTH_MAX_AGE_SECONDS`  | `30`                                                                     |
| `SCHEDULE_TIMEZONE`              | `Europe/Moscow`                                                          |
| `SCHEDULE_MISFIRE_GRACE_SECONDS` | `60`                                                                     |
| `SCHEDULE_COALESCE`              | `true`                                                                   |

`CHECK_DEPENDENCIES=false` и `RUN_BACKGROUND_WORKERS=false` используются в
юнит-тестах: сервис не подключается к PostgreSQL и RabbitMQ, health проверяет
только приложение.

## Локальный запуск

Все команды выполняются из корня репозитория.

```bash
make install
make env
make up
make migrate-scheduler
make run-scheduler
```

`make up` поднимает PostgreSQL, RabbitMQ, Mailpit, OTel Collector, Tempo,
Prometheus, Grafana и Loki. `make migrate-scheduler` создает схему `scheduler`,
таблицы `outbox`, `campaign_schedule` и `cancelled_campaign`.
`make run-scheduler` запускает uvicorn на порту 8002.

Без Makefile:

```bash
uv sync --all-packages
uv run alembic -c source/services/scheduler/alembic.ini upgrade head
uv run uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8002
```

## Проверка

Health:

```bash
curl -i http://localhost:8002/health
```

Пример ответа:

```json
{
  "status": "ok",
  "service": "scheduler",
  "version": "0.1.0",
  "uptime_seconds": 12.4,
  "checks": [
    {"name": "application", "status": "ok", "detail": "Сервис готов принимать запросы"},
    {"name": "database", "status": "ok", "detail": "PostgreSQL доступен"},
    {"name": "rabbitmq", "status": "ok", "detail": "Соединение с RabbitMQ установлено"},
    {"name": "scheduler", "status": "ok", "detail": "Планировщик заданий запущен"},
    {"name": "consumer", "status": "ok", "detail": "Потребитель команд обрабатывает очередь"},
    {"name": "outbox_relay", "status": "ok", "detail": "Outbox relay обрабатывает очередь"}
  ]
}
```

Если PostgreSQL или RabbitMQ недоступны, health возвращает 503. Если outbox
relay отстает, consumer сообщал об ошибке или восстановление заданий завершилось
ошибкой, итоговый статус становится `degraded`, а HTTP-код остается 200.

Swagger и сгенерированная схема:

- `http://localhost:8002/docs`
- `http://localhost:8002/openapi.json`

Источник истины для HTTP API: [scheduler.yaml](../../contracts/openapi/scheduler.yaml).
Контракты RabbitMQ: [loandebtors.yaml](../../contracts/asyncapi/loandebtors.yaml).

## Обмен сообщениями

Scheduler работает с topic exchange `loan-debtors.events`.

| Направление | Очередь                 | Routing key                                 |
|-------------|-------------------------|---------------------------------------------|
| Входящие    | `scheduler.commands`    | `campaign.scheduled`, `campaign.cancelled`  |
| Исходящие   | `notification.commands` | `campaign.start`                            |
| Исходящие   | `audit.events`          | `audit.event`                               |

Для каждой очереди объявлены durable-очередь, retry-очередь с TTL и DLQ.
Публикация выполняется с publisher confirms, `mandatory=True` и persistent
сообщениями. Повторы считаются по заголовку `x-death`; после исчерпания
`RABBITMQ_RETRY_MAX_ATTEMPTS` сообщение уходит в DLQ.

После истечения TTL RabbitMQ возвращает сообщение с routing key
`scheduler.commands`. Consumer принимает этот ключ и определяет тип события по
наличию поля `schedule` в теле: с полем это `campaign.scheduled`, без поля
`campaign.cancelled`.

## Хранение

Схема `scheduler` содержит:

- `campaign_schedule`: правило запуска, статус, `next_run_at`,
  `last_triggered_at`, корреляция исходной команды;
- `cancelled_campaign`: идемпотентная отметка отмены кампании, которая
  переживает порядок `campaign.cancelled` раньше `campaign.scheduled`;
- `outbox`: `campaign.start` и `audit.event` с маршрутизацией, заголовками,
  счетчиком попыток и временем публикации.

Задания APScheduler хранятся в памяти и восстанавливаются из `campaign_schedule`
при старте. Это рассчитано на один экземпляр сервиса.

## Мониторинг

При `OTEL_ENABLED=true` сервис экспортирует трейсы, метрики и логи по OTLP gRPC
в коллектор. На стенде Collector передает трейсы в Tempo, отдает метрики для
Prometheus, отправляет логи в Loki, а Grafana показывает все три вида данных.

- Collector: `http://localhost:4317`, метрики сервисов на `http://localhost:8889/metrics`
- Grafana: `http://localhost:3000`, по умолчанию `admin` / `admin`
- Prometheus: `http://localhost:9090`
- Loki: `http://localhost:3100`
- Tempo: `http://localhost:3200`

В Grafana открывайте дашборд `LoanDebtors Scheduler: Overview`.
Базовые запросы к Prometheus:

```promql
target_info{job="scheduler"}
sum by (http_route) (rate(loandebtors_scheduler_http_requests_total[5m]))
sum(rate(loandebtors_scheduler_consumer_messages_total[5m]))
sum(rate(loandebtors_scheduler_jobs_triggered_total[5m]))
```

Трейсы ищите в Explore с источником Tempo по сервису `scheduler`.
Доступность коллектора не влияет на health сервиса: телеметрия работает в
режиме best effort.

## Логи

Сервис пишет структурированные JSON-логи в stdout и одновременно отправляет их
по OTLP в Collector, который передает записи в Loki. Поля: `timestamp`, `level`,
`logger`, `message`, `service`, `service_version`, `environment`,
`correlation_id`, `trace_id`, `span_id`, `event`, HTTP-поля access-лога и
`exception` при ошибке.

Примеры LogQL:

```logql
{service_name="scheduler"}
```

```logql
{service_name="scheduler"} | json | level="ERROR"
```

```logql
{service_name="scheduler"} | json | campaign_id="3f0c1f5e-3d6a-4a7b-9c8d-1e2f3a4b5c6d"
```

Логи в Docker остаются доступны для локальной отладки:

```bash
docker compose -f source/infra/compose.yaml logs -f scheduler
```

Для SQL-логов задайте `DATABASE_ECHO=true`. Экспорт логов отключается
`OTEL_LOGS_ENABLED=false`. Access-логи health по умолчанию не пишутся; включить
их можно `ACCESS_LOG_HEALTH_ENABLED=true`.

## Тесты и проверки

Только Scheduler:

```bash
uv run pytest source/services/scheduler/tests -q
```

Отдельные наборы:

```bash
uv run pytest source/services/scheduler/tests/unit -q
uv run pytest source/services/scheduler/tests/bdd -q
```

Интеграционный тест поднимает PostgreSQL и RabbitMQ через Testcontainers,
применяет миграции и проверяет health, публикацию `campaign.start`, audit-события
и отмену расписания:

```bash
uv run pytest -m integration source/services/scheduler/tests/integration -q
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

Только Scheduler с зависимостями:

```bash
docker compose -f source/infra/compose.yaml up -d --build scheduler
curl http://localhost:8002/health
docker compose -f source/infra/compose.yaml logs -f scheduler
```

Полный стенд:

```bash
make up-all
```

Остановка:

```bash
make down
```

## Структура

```
src/scheduler/
├── domain/                 расписание, события, audit и ошибки
├── application/            сценарии расписания, срабатывания и восстановления
├── ports/                  репозиторий, задания, outbox, единица работы
├── adapters/http/          health, Problem и middleware
├── adapters/messaging/     RabbitMQ, consumer команд, публикатор и outbox relay
├── adapters/persistence/   PostgreSQL, модели, расписания, отметки отмены и outbox
├── adapters/scheduling/    APScheduler и health планировщика
└── infrastructure/         логирование, корреляция, метрики и телеметрия
```

Архитектурное описание: [5-building-block-view.md](../../../docs/arc42/5-building-block-view.md).
Доменная модель: [8-cross-cutting-concepts.md](../../../docs/arc42/8-cross-cutting-concepts.md), раздел 8.2.5.
Телеметрия: [8-cross-cutting-concepts.md](../../../docs/arc42/8-cross-cutting-concepts.md), раздел 8.4.
