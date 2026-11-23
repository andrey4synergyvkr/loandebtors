# ABS (заглушка)

Заглушка внешней АБС для локального учебного стенда. Она имитирует
постраничную выгрузку портфеля должников по контракту
[source/contracts/openapi/abs.yaml](../../contracts/openapi/abs.yaml).

Заглушка не входит в границу системы LoanDebtors и не является строительным
блоком архитектуры. Реальная АБС остаётся внешней системой, а контейнер `abs`
нужен для автономных прогонов, демонстраций и тестов адаптера Notifications.

## Что уже реализовано

- OpenAPI-контракт выгрузки должников;
- детерминированный JSON-фикстур из 24 вымышленных должников;
- постраничная выдача с `page`, `page_size`, `total` и `has_next`;
- фильтры `min_days_overdue`, `max_days_overdue` и `channel`;
- управляемые сценарии ошибок через заголовок `X-Stub-Scenario`;
- health с проверкой `application`;
- структурированные JSON-логи, HTTP-метрики и OTLP-экспорт;
- Docker Compose, Makefile и дашборд Grafana;
- модульные, BDD и интеграционные тесты.

## Требования

- Python 3.12;
- `uv`;
- Docker и Docker Compose для контейнерного запуска.

## Переменные окружения

Настройки читаются из переменных окружения и файла `.env` в корне репозитория.
Лишние переменные игнорируются.

| Переменная                    | Значение по умолчанию |
|-------------------------------|-----------------------|
| `SERVICE_NAME`                | `abs`                 |
| `ENVIRONMENT`                 | `local`               |
| `LOG_LEVEL`                   | `INFO`                |
| `HTTP_HOST`                   | `0.0.0.0`             |
| `HTTP_PORT`                   | `9000`                |
| `OTLP_ENDPOINT`               | `http://localhost:4317` |
| `OTEL_ENABLED`                | `false`               |
| `OTEL_LOGS_ENABLED`           | `true`                |
| `OTEL_INSECURE`               | `true`                |
| `OTEL_SAMPLE_RATIO`           | `1.0`                 |
| `OTEL_EXPORT_INTERVAL_SECONDS`| `10`                  |
| `ACCESS_LOG_HEALTH_ENABLED`   | `false`               |
| `ABS_STUB_TIMEOUT_SECONDS`    | `35`                  |

`ABS_STUB_TIMEOUT_SECONDS` используется только сценарием `timeout`. Значение по
умолчанию больше клиентского таймаута Notifications `ABS_TIMEOUT_SECONDS=30`.

## Эндпоинты

### GET /health

Возвращает 200 и проверку `application`, пока приложение готово принимать
запросы. До завершения инициализации и при остановке возвращает 503.

```json
{
  "status": "ok",
  "service": "abs",
  "version": "0.1.0",
  "uptime_seconds": 1.2,
  "checks": [
    {
      "name": "application",
      "status": "ok",
      "detail": "Сервис готов принимать запросы"
    }
  ]
}
```

### GET /v1/debtors

Параметры:

| Параметр           | Тип     | По умолчанию | Описание                                      |
|--------------------|---------|--------------|-----------------------------------------------|
| `page`             | integer | 1            | Номер страницы, начиная с 1                   |
| `page_size`        | integer | 500          | Размер страницы, от 1 до 1000                  |
| `min_days_overdue` | integer | нет          | Минимальное число дней просрочки              |
| `max_days_overdue` | integer | нет          | Максимальное число дней просрочки             |
| `channel`          | string  | нет          | Канал, по которому нужен контакт должника     |

Должник попадает в выборку, если хотя бы одна его задолженность удовлетворяет
диапазону просрочки, а контакт соответствует каналу. Неизвестные query-параметры
игнорируются.

Пример:

```bash
curl "http://localhost:9000/v1/debtors?page=1&page_size=5&min_days_overdue=30"
```

```json
{
  "items": [
    {
      "debtor_id": "ABS-100004",
      "full_name": "Тестовый Должник 04",
      "contacts": [
        {
          "channel": "email",
          "address": "debtor04@example.test",
          "is_primary": true
        }
      ],
      "debts": [
        {
          "contract_id": "CR-2024-0004",
          "amount": {
            "amount": "78120.75",
            "currency": "RUB"
          },
          "due_date": "2025-03-10",
          "days_overdue": 30
        }
      ]
    }
  ],
  "page": 1,
  "total": 21,
  "has_next": true
}
```

`total` означает число должников по всей выборке, а не размер страницы.

## Сценарии сбоев

Заголовок `X-Stub-Scenario` управляет поведением заглушки и не является частью
контракта АБС.

| Значение      | Поведение                                                        |
|---------------|------------------------------------------------------------------|
| `ok`          | Обычная страница, значение по умолчанию                          |
| `error_500`   | Ответ 500 в формате `application/problem+json`                    |
| `unavailable` | Ответ 503 в формате `application/problem+json`                    |
| `timeout`     | Задержка `ABS_STUB_TIMEOUT_SECONDS`, затем обычная страница       |
| `incomplete`  | Страница усекается на одного должника, `has_next=false`, `total` не меняется |

Неизвестное значение возвращает 400 в формате `application/problem+json`.

Примеры:

```bash
curl -i -H "X-Stub-Scenario: unavailable" "http://localhost:9000/v1/debtors?page=1"
curl -i -H "X-Stub-Scenario: error_500" "http://localhost:9000/v1/debtors?page=1"
curl -i -H "X-Stub-Scenario: incomplete" "http://localhost:9000/v1/debtors?page=1&page_size=5"
```

## Данные

Фикстур лежит в [src/abs/data/debtors.json](src/abs/data/debtors.json). Он
содержит 24 вымышленных должника, у каждого один или два долга. Данные
отсортированы по `debtor_id`, поэтому страницы детерминированы.

Чтобы изменить набор данных, отредактируйте JSON и перезапустите сервис.
Заглушка намеренно не использует PostgreSQL, RabbitMQ, Alembic и outbox. Это
отличает её от сервисов системы и не требует применения миграций.

## Запуск

Полный стенд, включая заглушку:

```bash
make install
make env
make up
```

`make up` поднимает инфраструктуру, Мониторинг и контейнер `abs`. Notifications
в Compose получает `ABS_BASE_URL=http://abs:9000`.

Локальный запуск заглушки без контейнера:

```bash
make run-abs
```

В этом случае Notifications, запущенный через `make run-notifications`,
использует `ABS_BASE_URL=http://localhost:9000` из `.env`.

Одновременно запускать контейнер `abs` и `make run-abs` нельзя, порт 9000 будет
занят.

## Проверка

```bash
make smoke-abs
curl "http://localhost:9000/v1/debtors?page=1&page_size=5"
```

Полный health:

```bash
curl -i http://localhost:9000/health
```

## Тесты

```bash
make test
make test-bdd
uv run pytest source/services/abs -m integration
```

Все тесты, включая интеграционные:

```bash
make test-all
```

Заглушка участвует в сквозных сценариях как источник должников:

```bash
make up-all
make e2e
```

Интеграционный тест запускает uvicorn на свободном порту и не требует Docker.

## Структура

```
source/services/abs/
├── pyproject.toml
├── README.md
├── src/abs/
│   ├── main.py
│   ├── config.py
│   ├── container.py
│   ├── application/health.py
│   ├── domain/debtor.py
│   ├── ports/catalog.py
│   ├── adapters/fixture.py
│   ├── adapters/http/
│   │   ├── constants.py
│   │   ├── health.py
│   │   ├── debtors.py
│   │   ├── problems.py
│   │   └── middleware.py
│   ├── infrastructure/
│   │   ├── correlation.py
│   │   ├── logging.py
│   │   ├── metrics.py
│   │   └── telemetry.py
│   └── data/debtors.json
└── tests/
    ├── unit/
    ├── bdd/
    └── integration/
```

## Ограничения

- заглушка не аутентифицирует запросы и предназначена только для доверенного
  учебного контура;
- реальная АБС и её инфраструктура не эмулируются, проверяется только контракт
  выгрузки;
- Notifications передаёт критерии `min_days_overdue`, `max_days_overdue` и
  `channel` query-параметрами, неизвестные параметры заглушка игнорирует;
- сценарии `X-Stub-Scenario` предназначены для тестов; production-адаптер
  Notifications классифицирует 4xx, 5xx, таймауты и сетевые ошибки сам.
