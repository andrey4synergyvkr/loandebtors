# Email Channel

Сервис Email Channel: настройка SMTP-адаптера, email-шаблоны, рендеринг и
отправка писем, публикация результатов доставки и audit-событий. Реализован
полный канал email: API настроек и шаблонов, consumer `email.commands`,
Jinja2-рендеринг, SMTP-отправка и rate limit.

## Что реализовано

- настройки сервиса, PostgreSQL через SQLAlchemy и Alembic;
- схема `email_channel`, таблицы `outbox`, `smtp_config`, `email_templates`,
  `send_attempts` и `processed_messages`;
- `GET /v1/config`, `PUT /v1/config`, `POST /v1/config/validate`;
- `GET /v1/templates`, `GET` и `PUT /v1/templates/{key}/versions/{version}`;
- consumer `email.commands` для `message.send` с manual ack, retry и DLQ;
- идемпотентность по `message_id` через `processed_messages`;
- Jinja2-рендеринг темы, HTML и текстовой части;
- SMTP-отправка через `aiosmtplib` и классификация ошибок;
- глобальный rate limiter канала;
- публикация `message.sent` и `message.failed` в `notification.results`;
- audit-события `channel.config.updated`, `message.sent` и `message.failed`;
- health с проверками `application`, `database`, `rabbitmq`, `outbox_relay`,
  `email_consumer`;
- Problem+JSON для 404, 409, 422 и 500;
- OTel traces, metrics, logs и структурированные JSON-логи;
- модульные и интеграционные тесты, включая Mailpit.

## Переменные окружения

Настройки читаются из переменных окружения и файла `.env` в корне репозитория.

| Переменная                          | Значение по умолчанию                                              |
|-------------------------------------|--------------------------------------------------------------------|
| `SERVICE_NAME`                      | `email_channel`                                                    |
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
| `HTTP_PORT`                         | `8003`                                                             |
| `OTLP_ENDPOINT`                     | `http://localhost:4317`                                            |
| `OTEL_ENABLED`                      | `false`                                                            |
| `OTEL_LOGS_ENABLED`                 | `true`                                                             |
| `OTEL_INSECURE`                     | `true`                                                             |
| `OTEL_SAMPLE_RATIO`                 | `1.0`                                                              |
| `OTEL_EXPORT_INTERVAL_SECONDS`      | `10`                                                               |
| `ACCESS_LOG_HEALTH_ENABLED`         | `false`                                                            |
| `HEALTH_CHECK_TIMEOUT_SECONDS`      | `3`                                                                |
| `CHECK_DEPENDENCIES`                | `true`                                                             |
| `RUN_BACKGROUND_WORKERS`            | `true`                                                             |
| `OUTBOX_POLL_INTERVAL_SECONDS`      | `1`                                                                |
| `OUTBOX_BATCH_SIZE`                 | `100`                                                              |
| `OUTBOX_MAX_ATTEMPTS`               | `10`                                                               |
| `OUTBOX_RETRY_BASE_SECONDS`         | `1`                                                                |
| `OUTBOX_RETRY_MAX_SECONDS`          | `60`                                                               |
| `OUTBOX_HEALTH_MAX_AGE_SECONDS`     | `30`                                                               |
| `SMTP_HOST`                         | `localhost`                                                        |
| `SMTP_PORT`                         | `1025`                                                             |
| `SMTP_USERNAME`                     | пусто                                                              |
| `SMTP_PASSWORD`                     | пусто                                                              |
| `SMTP_FROM`                         | `noreply@loandebtors.local`                                        |
| `SMTP_STARTTLS`                     | `false`                                                            |
| `SMTP_TIMEOUT_SECONDS`              | `30`                                                               |
| `RATE_LIMIT_PER_SECOND`             | `10`                                                               |
| `EMAIL_DEFAULT_LOCALE`              | `ru-RU`                                                            |
| `EMAIL_CONSUMER_RECONNECT_SECONDS`  | `5`                                                                |

## Локальный запуск

```bash
make install
make env
make up
make migrate-email-channel
make run-email-channel
```

`make up` поднимает PostgreSQL, RabbitMQ, Mailpit, OTel Collector, Tempo,
Prometheus, Grafana и Loki. `make migrate-email-channel` создает схему
`email_channel` и ее таблицы. `make run-email-channel` запускает uvicorn на
порту 8003.

Без Makefile:

```bash
uv sync --all-packages
uv run alembic -c source/services/email_channel/alembic.ini upgrade head
uv run uvicorn email_channel.main:app --reload --host 0.0.0.0 --port 8003
```

## Проверка

Health:

```bash
curl -i http://localhost:8003/health
```

Настройки канала:

```bash
curl -X PUT http://localhost:8003/v1/config \
  -H "Content-Type: application/json" \
  -d '{
    "host": "smtp.example.com",
    "port": 587,
    "username": "user",
    "password_ref": "SMTP_PASSWORD",
    "from_address": "noreply@example.com",
    "from_name": "Bank",
    "use_starttls": true,
    "timeout_seconds": 30,
    "rate_limit_per_second": 10,
    "enabled": true
  }'

curl -i http://localhost:8003/v1/config
```

Проверка без сохранения:

```bash
curl -X POST http://localhost:8003/v1/config/validate \
  -H "Content-Type: application/json" \
  -d '{
    "host": "localhost",
    "port": 1025,
    "username": "user",
    "password_ref": "SMTP_PASSWORD",
    "from_address": "noreply@example.com",
    "from_name": "Bank",
    "use_starttls": false,
    "timeout_seconds": 5,
    "rate_limit_per_second": 10,
    "enabled": true
  }'
```

Email-шаблон:

```bash
curl -X PUT http://localhost:8003/v1/templates/payment-reminder/versions/1 \
  -H "Content-Type: application/json" \
  -d '{
    "locale": "ru-RU",
    "subject_template": "Напоминание {{ name }}",
    "html_template": "<p>Здравствуйте, {{ name }}</p>",
    "plain_text_template": "Здравствуйте, {{ name }}",
    "required_variables": ["name"]
  }'

curl "http://localhost:8003/v1/templates?limit=10"
curl "http://localhost:8003/v1/templates/payment-reminder/versions/1?locale=ru-RU"
```

После сохранения настроек или шаблона в `email_channel.outbox` появляется
`audit.event`, relay публикует его в `audit.events`, Audit Exporter записывает
журнал.

Swagger:

- `http://localhost:8003/docs`
- `http://localhost:8003/openapi.json`

Источник истины: [email-channel.yaml](../../contracts/openapi/email-channel.yaml).
Контракты RabbitMQ: [loandebtors.yaml](../../contracts/asyncapi/loandebtors.yaml).

## Обмен сообщениями

| Направление | Очередь              | Routing key                 |
|-------------|----------------------|-----------------------------|
| Входящие    | `email.commands`     | `message.send`              |
| Исходящие   | `notification.results` | `message.sent`, `message.failed` |
| Исходящие   | `audit.events`       | `audit.event`               |

Consumer `email.commands` работает с manual ack и prefetch. Ошибка валидации
уходит в `email.commands.dlq`, ошибка БД возвращает сообщение в retry-очередь.
При исчерпании повторов Email Channel публикует `message.failed` с
`retryable=false` и отправляет исходную команду в DLQ, чтобы Notifications не
оставил сообщение в `queued`. Результат SMTP-отправки публикуется в
`notification.results` через outbox. Повторная доставка уже обработанного
`message.send` не отправляет письмо второй раз: `message_id` фиксируется в
`processed_messages` после успешной отправки или постоянной ошибки. Временная
ошибка и `rate_limited` не фиксируются, поэтому повторная команда от
Notifications снова доходит до SMTP. Если настройки не сохранены через API,
доставка использует значения `SMTP_*` из окружения.

## Тесты

```bash
uv run pytest source/services/email_channel/tests/unit -q
uv run pytest -m integration source/services/email_channel/tests/integration -q
uv run pytest -m integration source/services/audit_exporter/tests/integration -q
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

Линтер, типы и быстрые тесты:

```bash
make check
```

Интеграционный набор Email Channel поднимает PostgreSQL, RabbitMQ и Mailpit,
проверяет `message.send` -> SMTP -> `notification.results` и `audit.events`.
Набор Audit Exporter проверяет сквозной путь до `GET /v1/audit-records`.

## Запуск в Docker

Только Email Channel с зависимостями:

```bash
docker compose -f source/infra/compose.yaml up -d --build email-channel
curl http://localhost:8003/health
docker compose -f source/infra/compose.yaml logs -f email-channel
```

Полный стенд из корня репозитория:

```bash
docker compose up -d --build
```

Остановка:

```bash
make down
```

## Ограничения

- канал реализует только email;
- повторные попытки выполняет Notifications по `message.failed.retryable`;
- доставка работает по модели at-least-once: при сбое между ответом SMTP и
  записью результата сообщение может быть отправлено повторно;
- аутентификация и авторизация не выполняются по OC-2;
- сервис рассчитан на один экземпляр в учебном стенде.
