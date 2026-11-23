# Notifications

Сервис Notifications: кампании рассылки, логические шаблоны, снимки должников и
состояние сообщений. Реализованы этапы 0-6: инфраструктура, телеметрия,
Docker Compose, честный health, управление шаблонами и кампаниями, планирование,
отмена, запуск, полная выборка должников через АБС, обработка результатов
отправки, повторы, восстановление и retention. Все маршруты OpenAPI реализованы.

## Что уже реализовано

- настройки сервиса, PostgreSQL через SQLAlchemy и Alembic;
- таблица `notification.outbox` и фоновый outbox relay с publisher confirms;
- подключение к RabbitMQ, топология exchange, очередей, retry-очередей и DLQ;
- таблица `notification.templates` и API логических шаблонов;
- таблица `notification.campaigns` и API кампаний до запуска;
- планирование и отмена кампании с событиями `campaign.scheduled` и
  `campaign.cancelled` в outbox;
- проверка активной версии шаблона при создании и изменении кампании;
- потребитель `campaign.start` с retry через очередь и DLQ;
- полная постраничная выборка АБС с проверкой `total`, дублей и лимита 10 000;
- таблицы `notification.debtor_snapshots` и `notification.messages`;
- создание сообщений и команд `message.send` в транзакционном outbox;
- потребитель `message.sent`/`message.failed` с retry через очередь и DLQ;
- таблица `notification.message_attempts` и история попыток;
- повторы через outbox с `available_at = next_attempt_at`;
- завершение кампании после обработки всех сообщений;
- отмена выполняющейся кампании с отменой неотправленных сообщений;
- API просмотра сообщений кампании;
- фоновое обслуживание: retention outbox и попыток, повторная постановка
  зависших сообщений и кампаний, завершение кампаний;
- graceful shutdown с ожиданием активных обработчиков;
- дашборд Delivery и алерты Prometheus по DLQ, ошибкам и восстановлению;
- транзакционная единица работы `UnitOfWork` для состояния и audit-событий;
- аудит `template.*`, `campaign.*`, `message.*` через outbox;
- провайдеры OpenTelemetry `TracerProvider`, `MeterProvider` и `LoggerProvider`;
- OTLP gRPC для трейсов, метрик и логов;
- инструментирование FastAPI, SQLAlchemy, asyncpg и httpx;
- структурированное JSON-логирование с `trace_id`, `span_id`, корреляцией и
  HTTP-полями access-лога;
- экспорт логов в Collector и Loki, просмотр в Grafana;
- health с проверками `application`, `database`, `rabbitmq`, `outbox_relay`,
  `campaign_consumer`, `message_result_consumer`, `maintenance`;
- модульные, BDD и интеграционные тесты.

## Требования

- Python 3.12;
- `uv`;
- Docker и Docker Compose для инфраструктуры, мониторинга и контейнерного запуска.

## Переменные окружения

Настройки читаются из переменных окружения и файла `.env` в корне репозитория.
Для локального запуска достаточно значений по умолчанию, но для health 200
нужны PostgreSQL и RabbitMQ.

| Переменная                        | Значение по умолчанию                                              |
|-----------------------------------|--------------------------------------------------------------------|
| `SERVICE_NAME`                    | `notifications`                                                    |
| `ENVIRONMENT`                     | `local`                                                            |
| `LOG_LEVEL`                       | `INFO`                                                             |
| `DATABASE_URL`                    | `postgresql+asyncpg://loandebtors:loandebtors@localhost:5432/loandebtors` |
| `DATABASE_ECHO`                   | `false`                                                            |
| `DATABASE_POOL_SIZE`              | `5`                                                                |
| `DATABASE_MAX_OVERFLOW`           | `5`                                                                |
| `RABBITMQ_URL`                    | `amqp://loandebtors:loandebtors@localhost:5672/`                   |
| `RABBITMQ_CONNECTION_TIMEOUT`     | `10`                                                               |
| `RABBITMQ_PREFETCH_COUNT`         | `50`                                                               |
| `RABBITMQ_RETRY_TTL_SECONDS`      | `60`                                                               |
| `RABBITMQ_RETRY_MAX_ATTEMPTS`     | `10`                                                               |
| `HTTP_HOST`                       | `0.0.0.0`                                                          |
| `HTTP_PORT`                       | `8001`                                                             |
| `OTLP_ENDPOINT`                   | `http://localhost:4317`                                            |
| `OTEL_ENABLED`                    | `false`                                                            |
| `OTEL_LOGS_ENABLED`               | `true`                                                             |
| `OTEL_INSECURE`                   | `true`                                                             |
| `OTEL_SAMPLE_RATIO`               | `1.0`                                                              |
| `OTEL_EXPORT_INTERVAL_SECONDS`    | `10`                                                               |
| `ACCESS_LOG_HEALTH_ENABLED`       | `false`                                                            |
| `CHECK_DEPENDENCIES`              | `true`                                                             |
| `RUN_BACKGROUND_WORKERS`          | `true`                                                             |
| `HEALTH_CHECK_TIMEOUT_SECONDS`    | `3`                                                                |
| `OUTBOX_POLL_INTERVAL_SECONDS`    | `1`                                                                |
| `OUTBOX_BATCH_SIZE`               | `100`                                                              |
| `OUTBOX_MAX_ATTEMPTS`             | `10`                                                               |
| `OUTBOX_RETRY_BASE_SECONDS`       | `1`                                                                |
| `OUTBOX_RETRY_MAX_SECONDS`        | `60`                                                               |
| `OUTBOX_HEALTH_MAX_AGE_SECONDS`   | `30`                                                               |
| `ABS_BASE_URL`                    | `http://localhost:9000`                                            |
| `ABS_TIMEOUT_SECONDS`             | `30`                                                               |
| `ABS_MAX_ATTEMPTS`                | `3`                                                                |
| `ABS_RETRY_BASE_SECONDS`          | `0.5`                                                              |
| `DEBTOR_PAGE_SIZE`                | `500`                                                              |
| `DEBTOR_SELECTION_MAX_TOTAL`      | `10000`                                                            |
| `MESSAGE_MAX_ATTEMPTS`            | `3`                                                                |
| `MESSAGE_RETRY_BASE_SECONDS`      | `30`                                                               |
| `MESSAGE_RETRY_MAX_SECONDS`       | `3600`                                                             |
| `RETENTION_DAYS`                  | `30`                                                               |
| `MAINTENANCE_INTERVAL_SECONDS`    | `3600`                                                             |
| `RECOVERY_GRACE_SECONDS`          | `300`                                                              |
| `MAINTENANCE_BATCH_SIZE`          | `100`                                                              |
| `MAINTENANCE_HEALTH_MAX_AGE_SECONDS` | `7200`                                                          |

`CHECK_DEPENDENCIES=false` и `RUN_BACKGROUND_WORKERS=false` используются в
юнит-тестах: сервис не подключается к PostgreSQL и RabbitMQ, health проверяет
только приложение.

## Локальный запуск

Все команды выполняются из корня репозитория.

```bash
make install
make env
make up
make migrate
make run-notifications
```

`make up` поднимает PostgreSQL, RabbitMQ, Mailpit, OTel Collector, Tempo,
Prometheus, Grafana и Loki. `make migrate` применяет миграции всех сервисов,
включая схему `notification` и таблицы `outbox`, `templates`, `campaigns`,
`debtor_snapshots`, `messages` и `message_attempts`.
`make run-notifications` запускает uvicorn на порту 8001.

Без Makefile:

```bash
uv sync --all-packages
uv run alembic -c source/services/notifications/alembic.ini upgrade head
uv run uvicorn notifications.main:app --reload --host 0.0.0.0 --port 8001
```

## Проверка

Health:

```bash
curl -i http://localhost:8001/health
```

Пример ответа:

```json
{
  "status": "ok",
  "service": "notifications",
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
      "name": "outbox_relay",
      "status": "ok",
      "detail": "Outbox relay обрабатывает очередь"
    },
    {
      "name": "campaign_consumer",
      "status": "ok",
      "detail": "Консьюмер campaign.start принимает сообщения"
    },
    {
      "name": "message_result_consumer",
      "status": "ok",
      "detail": "Консьюмер notification.results принимает сообщения"
    },
    {
      "name": "maintenance",
      "status": "ok",
      "detail": "Обслуживание выполняет итерации"
    }
  ]
}
```

Если PostgreSQL или RabbitMQ недоступны, health возвращает 503. Если outbox
relay отстаёт или последняя итерация завершилась ошибкой, итоговый статус
становится `degraded`, а HTTP-код остаётся 200.

## Логические шаблоны

Реализованы маршруты `GET /v1/templates`, `POST /v1/templates`,
`GET /v1/templates/{template_key}` и
`PATCH /v1/templates/{template_key}/versions/{version}`.

Создать версию шаблона:

```bash
curl -sS -X POST http://localhost:8001/v1/templates \
  -H 'Content-Type: application/json' \
  -d '{
    "key": "payment-reminder",
    "version": 1,
    "description": "Напоминание об оплате",
    "required_variables": ["debtor_name", "amount"]
  }'
```

Ответ 201:

```json
{
  "key": "payment-reminder",
  "version": 1,
  "description": "Напоминание об оплате",
  "required_variables": ["debtor_name", "amount"],
  "status": "draft",
  "created_at": "2026-11-22T12:00:00Z",
  "updated_at": "2026-11-22T12:00:00Z"
}
```

Активировать версию и получить активную версию:

```bash
curl -sS -X PATCH \
  http://localhost:8001/v1/templates/payment-reminder/versions/1 \
  -H 'Content-Type: application/json' \
  -d '{"status": "active"}'

curl -sS http://localhost:8001/v1/templates/payment-reminder
```

Список с фильтром и страницей:

```bash
curl -sS 'http://localhost:8001/v1/templates?status=active&limit=50&offset=0'
```

Правила жизненного цикла:

- новая версия создается в статусе `draft`;
- активная версия у ключа может быть только одна, активация новой версии
  переводит предыдущую в `archived`;
- переходы `draft -> active`, `draft -> archived` и `active -> archived`
  разрешены, `archived` окончателен;
- повтор текущего статуса считается успешным и не создает audit-событие;
- создание и смена статуса пишут `template.created` и
  `template.status.changed` в `notification.outbox` в той же транзакции;
- ошибки возвращаются как `application/problem+json`: 404 для отсутствующей
  версии, 409 для конфликта уникальности или запрещенного перехода, 422 для
  недопустимых полей.

## Кампании

Реализованы маршруты `GET /v1/campaigns`, `POST /v1/campaigns`,
`GET /v1/campaigns/{campaign_id}` и `PATCH /v1/campaigns/{campaign_id}`,
а также запуск, расписание, отмена и просмотр сообщений кампании.

Создать кампанию можно только с активной версией шаблона:

```bash
curl -sS -X POST http://localhost:8001/v1/campaigns \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Напоминание о просрочке",
    "channel": "email",
    "template_key": "payment-reminder",
    "template_version": 1,
    "selection": {
      "criteria": {"min_days_overdue": "30"}
    }
  }'
```

Ответ 201 содержит статус `draft`, пустые счетчики выгрузки и `schedule: null`.
Если версия шаблона отсутствует или не активна, возвращается 409.

Получить и изменить кампанию:

```bash
curl -sS http://localhost:8001/v1/campaigns/<campaign_id>

curl -sS -X PATCH http://localhost:8001/v1/campaigns/<campaign_id> \
  -H 'Content-Type: application/json' \
  -d '{"name": "Новое имя кампании"}'
```

Список с фильтром по статусу:

```bash
curl -sS 'http://localhost:8001/v1/campaigns?status=draft&limit=50&offset=0'
```

Правила:

- кампания создается в статусе `draft`;
- канал в первой версии только `email`;
- выбранная версия шаблона должна существовать и быть активной;
- изменять можно только поля кампании в статусе `draft`;
- ключ и версия шаблона в PATCH передаются вместе;
- создание и изменение пишут `campaign.created` и `campaign.updated` в
  `notification.outbox` в той же транзакции;
- ошибки возвращаются как `application/problem+json`: 404 для отсутствующей
  кампании, 409 для неактивного шаблона или изменения вне `draft`, 422 для
  недопустимых полей.

## Планирование и отмена

Поставить draft-кампанию в расписание:

```bash
curl -sS -X POST \
  http://localhost:8001/v1/campaigns/<campaign_id>/schedule \
  -H 'Content-Type: application/json' \
  -d '{
    "schedule": {
      "kind": "one_off",
      "timezone": "Europe/Moscow",
      "run_at": "2026-12-01T10:00:00Z"
    }
  }'
```

Ответ 202 содержит статус `scheduled`, сохраненное расписание и
`scheduled_at`. Для повторяющегося запуска используйте `kind: cron` и
пятипольное выражение в поле `cron` вместо `run_at`.

Отменить запланированную кампанию:

```bash
curl -sS -X POST \
  http://localhost:8001/v1/campaigns/<campaign_id>/cancel
```

Ответ 202 содержит статус `cancelled`, `cancelled_at` и `finished_at`.

Правила:

- планировать можно только кампанию в статусе `draft`;
- для `one_off` обязателен `run_at` с часовым поясом в будущем;
- для `cron` обязательны пятипольное выражение и часовой пояс IANA;
- отменять можно запланированную или выполняющуюся кампанию;
- планирование пишет `campaign.scheduled` в outbox и audit-событие с тем же
  действием;
- отмена пишет `campaign.cancelled` в outbox и audit-событие с тем же
  действием;
- оба события уходят в очередь `scheduler.commands` через транзакционный
  outbox, отдельная публикация из обработчика не выполняется;
- ошибки: 404 для отсутствующей кампании, 409 для недопустимого статуса,
  422 для некорректного расписания.

## Запуск и выборка

Немедленный запуск draft-кампании:

```bash
curl -sS -X POST \
  http://localhost:8001/v1/campaigns/<campaign_id>/start
```

Ответ 202 содержит статус `running` и `started_at`. В той же транзакции в outbox
пишется `campaign.start`, а audit-журнал получает `campaign.started`.

Потребитель `campaign.start` выполняет полную выгрузку:

- критерии `min_days_overdue`, `max_days_overdue` и `channel` отображаются в
  query-параметры АБС, неизвестные ключи игнорируются с предупреждением;
- страницы запрашиваются по порядку до `has_next=false`;
- проверяются стабильность `total`, отсутствие дублей `debtor_id`, совпадение
  числа должников с `total` и лимит `DEBTOR_SELECTION_MAX_TOTAL`;
- при неполной или противоречивой выборке снимки не сохраняются, кампания
  переходит в `failed`;
- снимки должников сохраняются в `notification.debtor_snapshots`, сообщения в
  `notification.messages`, команды `message.send` в `notification.outbox`;
- должники без контакта канала пропускаются, отметка `messages_created_at`
  фиксирует завершение создания сообщений;
- параллельная обработка одной кампании защищена advisory-блокировкой;
- временные ошибки АБС возвращают сообщение в retry-очередь, постоянные 4xx
  переводят кампанию в `failed`.

Проверить результат:

```bash
curl -sS http://localhost:8001/v1/campaigns/<campaign_id>
```

У запущенной кампании заполнены `selected_debtors`, `selection_expected` и
`selection_completed_at`.

## Результаты и повторы

Потребитель `notification.results` принимает `message.sent` и `message.failed`:

- успешный результат переводит сообщение в `sent`, пишет попытку и
  audit-событие `message.sent`;
- временная ошибка возвращает сообщение в `queued`, заполняет `next_attempt_at`
  и пишет отложенный `message.send` в outbox с `available_at` из
  `next_attempt_at`;
- постоянная ошибка или исчерпание `MESSAGE_MAX_ATTEMPTS` переводит сообщение в
  `failed` и пишет `message.failed`;
- задержка повтора растет экспоненциально от `MESSAGE_RETRY_BASE_SECONDS` до
  `MESSAGE_RETRY_MAX_SECONDS`;
- после обработки всех сообщений кампания переходит в `completed`, в audit
  пишется `campaign.completed` со счетчиками `sent`, `failed` и `cancelled`;
- повторная доставка результата и результат по отмененному сообщению
  игнорируются.

Отмена выполняющейся кампании переводит неотправленные сообщения в `cancelled`,
заполняет `cancelled_at` и `finished_at` и пишет audit-событие
`campaign.cancelled`.

## Сообщения

Список сообщений кампании:

```bash
curl -sS \
  'http://localhost:8001/v1/campaigns/<campaign_id>/messages?status=queued&limit=50&offset=0'
```

Сообщение по идентификатору:

```bash
curl -sS \
  http://localhost:8001/v1/campaigns/<campaign_id>/messages/<message_id>
```

Ответ содержит статус, счетчики попыток, время следующей попытки, коды ошибок и
снимок получателя. Ошибки: 404 для отсутствующей кампании или сообщения,
422 для недопустимых параметров страницы.

Swagger и сгенерированная схема:

- `http://localhost:8001/docs`
- `http://localhost:8001/openapi.json`

Источник истины для API: [notifications.yaml](../../contracts/openapi/notifications.yaml).
Контракты RabbitMQ: [loandebtors.yaml](../../contracts/asyncapi/loandebtors.yaml).

## Мониторинг

При `OTEL_ENABLED=true` сервис экспортирует трейсы, метрики и логи по OTLP gRPC
в коллектор. На стенде Collector передаёт трейсы в Tempo, отдаёт метрики для
Prometheus, отправляет логи в Loki, а Grafana показывает все три вида данных.

- Collector: `http://localhost:4317`, внутренние метрики на `http://localhost:8888/metrics`, метрики сервисов на `http://localhost:8889/metrics`
- Grafana: `http://localhost:3000`, по умолчанию `admin` / `admin`
- Prometheus: `http://localhost:9090`
- Loki: `http://localhost:3100`
- Tempo: `http://localhost:3200`

Полный список интерфейсов, учётных данных и команда сброса пароля Grafana
приведены в [корневом README](../../../README.md).

В Grafana открывайте дашборды `LoanDebtors Notifications: Overview`,
`HTTP`, `Outbox`, `Delivery`, `Logs`, `Traces` или `LoanDebtors Monitoring: Stack`.
Базовые запросы к Prometheus:

```promql
target_info{job="notifications"}
sum by (http_route) (rate(loandebtors_notifications_http_requests_total[5m]))
```

Трейсы ищите в Explore с источником Tempo по сервису `notifications`.
Доступность коллектора не влияет на health сервиса: телеметрия работает в
режиме best effort.

## Логи

Сервис пишет структурированные JSON-логи в stdout и одновременно отправляет их
по OTLP в Collector, который передаёт записи в Loki. Поля: `timestamp`, `level`,
`logger`, `message`, `service`, `service_version`, `environment`,
`correlation_id`, `trace_id`, `span_id`, `event`, HTTP-поля access-лога и
`exception` при ошибке.

В Grafana:

- Explore с источником `Loki`;
- дашборд `LoanDebtors Notifications: Logs`;
- ссылка `TraceID` в строке лога открывает соответствующий трейс в Tempo.

Примеры LogQL:

```logql
{service_name="notifications"}
```

```logql
{service_name="notifications"} | json | level="ERROR"
```

```logql
{service_name="notifications"} | json | http_route="/v1/campaigns"
```

Логи в Docker остаются доступны для локальной отладки:

```bash
docker compose -f source/infra/compose.yaml logs -f notifications
```

При локальном запуске логи выводятся в терминал `make run-notifications`.
Последние строки без follow:

```bash
docker compose -f source/infra/compose.yaml logs --tail=200 notifications
```

Для SQL-логов задайте `DATABASE_ECHO=true`. Логи миграций Alembic видны при
старте контейнера. Экспорт логов отключается `OTEL_LOGS_ENABLED=false`.
Access-логи health по умолчанию не пишутся; включить их можно
`ACCESS_LOG_HEALTH_ENABLED=true`.

## Тесты и проверки

Только Notifications:

```bash
uv run pytest source/services/notifications/tests -q
```

Отдельные наборы:

```bash
uv run pytest source/services/notifications/tests/unit -q
uv run pytest source/services/notifications/tests/bdd -q
```

Интеграционный тест поднимает PostgreSQL и RabbitMQ через Testcontainers,
применяет миграции и проверяет полный health:

```bash
uv run pytest -m integration source/services/notifications/tests/integration -q
```

Сквозной сценарий на полном стенде:

```bash
make up-all
make e2e
```

Линтер, типы и быстрые тесты:

```bash
make check
```

Все тесты, включая интеграционные:

```bash
make test-all
```

Или по отдельности:

```bash
uv run ruff check source/services/notifications/src source/services/notifications/tests
uv run ruff format --check source/services/notifications/src source/services/notifications/tests
uv run mypy source/services
uv run pytest
```

## Запуск в Docker

Только Notifications с зависимостями:

```bash
docker compose -f source/infra/compose.yaml up -d --build notifications
curl http://localhost:8001/health
docker compose -f source/infra/compose.yaml logs -f notifications
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
src/notifications/
├── domain/                 контракты домена, статусы, события и значения
├── application/            health, кампании, запуск, выборка, результаты и композиция
├── ports/                  репозитории, UnitOfWork, очередь, АБС, аудит и outbox
├── adapters/abs/           HTTP-адаптер выгрузки должников из АБС
├── adapters/http/          health, шаблоны, кампании, сообщения и Problem
├── adapters/messaging/     RabbitMQ, топология, consumers, публикатор и relay
├── adapters/persistence/   PostgreSQL, модели, репозитории, UoW и outbox
└── infrastructure/         логирование, корреляция, трейсы, метрики и телеметрия
```

Архитектурное описание: [5-building-block-view.md](../../../docs/arc42/5-building-block-view.md).
Телеметрия: [8-cross-cutting-concepts.md](../../../docs/arc42/8-cross-cutting-concepts.md), раздел 8.4.

## Нагрузочный сценарий

Проверка кампании на 10 000 должников без обращения к внешней АБС:

```bash
PYTHONPATH=source/services/notifications/src \
  uv run python source/services/notifications/tests/load/load_10k.py
```

Сценарий требует PostgreSQL из compose на `localhost:5432`, создает уникальные
шаблон и кампанию, печатает время и счетчики, после чего удаляет данные.
