# LoanDebtors

Учебная система уведомления должников. Сервис получает портфель должников из АБС,
формирует кампании и отправляет письма через внешнего почтового провайдера,
ведёт append-only журнал аудита и экспортирует метрики и трейсы.

Архитектура описана в [arc42](docs/arc42/README.md), диаграммы в [c4](docs/c4/README.md).

## Состав репозитория

| Каталог или файл    | Содержимое                                                                                               |
|---------------------|----------------------------------------------------------------------------------------------------------|
| `compose.yaml`      | Общий Docker Compose: подключает инфраструктуру и сервисы                                                |
| `source/services`   | Четыре сервиса: Notifications, Scheduler, Email Channel, Audit Exporter, а также заглушка АБС для стенда |
| `source/contracts`  | Контракты OpenAPI и AsyncAPI                                                                             |
| `source/acceptance` | Сквозные E2E-тесты на полном Docker-стенде                                                               |
| `source/infra`      | Docker Compose, конфигурация OTel, Loki, Prometheus, Tempo и Grafana, общий Dockerfile                   |
| `docs`              | Архитектурная документация ARC42, ADR и диаграммы C4                                                     |

## Стек

- Python 3.12
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- aio-pika
- APScheduler
- Jinja2
- Punq
- OpenTelemetry
- Grafana Tempo
- Loki
- Prometheus
- Grafana
- pytest
- Ruff
- mypy
- uv
- Docker Compose.

## Быстрый старт

Полный стенд в Docker:

```bash
make install
make env
make up-all
make smoke
```

То же самое без Makefile, из корня репозитория:

```bash
docker compose up -d --build
```

Корневой `compose.yaml` подключает общий файл `source/infra/compose.yaml`,
поэтому одной командой запускаются PostgreSQL, RabbitMQ, Mailpit, Мониторинг,
заглушка АБС и все четыре сервиса.

После запуска:

- Notifications: http://localhost:8001/health
- Grafana: http://localhost:3000, пользователь и пароль `admin` / `admin`
- Prometheus: http://localhost:9090
- Tempo: http://localhost:3200
- Mailpit: http://localhost:8025

Локальный запуск Notifications с инфраструктурой в Docker:

```bash
make install
make env
make up
make migrate
make run-notifications
make smoke
```

`make up` поднимает PostgreSQL, RabbitMQ, Mailpit, OTel Collector, Tempo,
Prometheus, Grafana, Loki и заглушку АБС. `make migrate` применяет миграции всех
сервисов. `make smoke` проверяет `/health` Notifications.

Сервисы доступны на портах:

| Сервис         | Порт | Модуль                    |
|----------------|------|---------------------------|
| Notifications  | 8001 | `notifications.main:app`  |
| Scheduler      | 8002 | `scheduler.main:app`      |
| Email Channel  | 8003 | `email_channel.main:app`  |
| Audit Exporter | 8004 | `audit_exporter.main:app` |
| ABS (заглушка) | 9000 | `abs.main:app`            |

Инфраструктура Мониторинга:

| Компонент      | Порт            | Назначение                              |
|----------------|-----------------|-----------------------------------------|
| OTel Collector | 4317, 4318, 8888, 8889 | OTLP gRPC, OTLP HTTP, внутренние метрики, метрики Prometheus |
| Loki           | 3100            | Приём и хранение логов                   |
| Tempo          | 3200            | HTTP API трейсов                        |
| Prometheus     | 9090            | Метрики и запросы PromQL                |
| Grafana        | 3000            | Дашборды и Explore                      |

### Доступ к веб-интерфейсам

Перед входом стенд должен быть запущен:

```bash
make up-all
```

| Интерфейс            | Адрес                          | Вход                                      |
|----------------------|--------------------------------|-------------------------------------------|
| Grafana              | http://localhost:3000          | `admin` / `admin`                         |
| Loki                 | http://localhost:3100          | Без входа, отдельного UI нет               |
| Prometheus           | http://localhost:9090          | Без входа                                 |
| Tempo                | http://localhost:3200          | Без входа, отдельного UI нет               |
| Mailpit              | http://localhost:8025          | Без входа                                 |
| RabbitMQ Management  | http://localhost:15672         | `loandebtors` / `loandebtors`             |
| Notifications Swagger| http://localhost:8001/docs     | Без входа                                 |
| Scheduler Swagger    | http://localhost:8002/docs     | Без входа                                 |
| Email Channel Swagger| http://localhost:8003/docs     | Без входа                                 |
| Audit Exporter Swagger| http://localhost:8004/docs    | Без входа                                 |
| ABS Swagger          | http://localhost:9000/docs    | Без входа                                 |
| OTel Collector       | http://localhost:8889/metrics  | Без входа, отдельного UI нет               |

Учётные данные Grafana задаются переменными `GRAFANA_ADMIN_USER` и
`GRAFANA_ADMIN_PASSWORD` в `.env`. Значения по умолчанию: `admin` / `admin`.
При первом входе Grafana может попросить сменить пароль. Если пароль был
изменён в UI, используйте новый пароль. Сбросить пароль администратора можно
командой:

```bash
docker exec -it loandebtors-grafana-1 grafana cli admin reset-admin-password admin
```

Команда меняет только пароль администратора, данные Grafana и дашборды
остаются на месте.

Учётные данные RabbitMQ задаются переменными `RABBITMQ_DEFAULT_USER` и
`RABBITMQ_DEFAULT_PASS`, по умолчанию `loandebtors` / `loandebtors`. Prometheus,
Tempo, Mailpit, OTel Collector и Swagger-страницы сервисов в учебном стенде
работают без аутентификации.

Проверка работоспособности: `GET /health`. Notifications возвращает 200 только
когда доступны PostgreSQL и RabbitMQ, работают outbox relay, consumers
`campaign.start` и `notification.results` и maintenance worker. Audit Exporter
возвращает 200, когда доступны PostgreSQL и RabbitMQ и запущен консьюмер
`audit.events`. Email Channel возвращает 200, когда доступны PostgreSQL и
RabbitMQ, работает outbox relay и запущен консьюмер `email.commands`. Scheduler
возвращает 200, когда доступны PostgreSQL и RabbitMQ, работают consumer
`scheduler.commands`, планировщик APScheduler и outbox relay. Если зависимость
недоступна, ответ будет 503.

Если dependent-проверка сообщает `degraded` (отставание outbox relay, ошибка
consumer или maintenance), итоговый статус тоже `degraded`, а HTTP-код остается
200. Код 503 означает недоступность обязательной зависимости.

## Как посмотреть метрики и трейсы

1. Откройте Grafana: http://localhost:3000.
2. Войдите как `admin` / `admin` или используйте значения
   `GRAFANA_ADMIN_USER` и `GRAFANA_ADMIN_PASSWORD` из `.env`.
3. Откройте дашборд `LoanDebtors Notifications` в папке `LoanDebtors`.
4. Для произвольного запроса откройте Explore, выберите источник `Prometheus`
   и выполните, например:

```promql
target_info{job="notifications"}
```

```promql
sum by (http_route) (rate(loandebtors_notifications_http_requests_total[5m]))
```

5. Для трейсов откройте Explore, выберите источник `Tempo` и найдите трейсы
   по сервису `notifications`.
6. Для логов откройте Explore, выберите источник `Loki` и выполните:

```logql
{service_name="notifications"} | json | level="ERROR"
```

Если в строке лога есть `trace_id`, в ней появится ссылка `TraceID` на
соответствующий трейс в Tempo.

### Дашборды Grafana

В папке `LoanDebtors` доступны дашборды:

| Дашборд | Что показывает |
|---|---|
| `LoanDebtors Notifications: Overview` | Общее состояние сервиса, HTTP, outbox, атрибуты и последние логи |
| `LoanDebtors Notifications: HTTP` | Запросы по маршрутам, кодам ответа, методы и латентность |
| `LoanDebtors Notifications: Outbox` | Публикации, ошибки, размер пачки и длительность relay |
| `LoanDebtors Notifications: Delivery` | Consumer, повторы, DLQ, размер выборки и работа восстановления |
| `LoanDebtors Notifications: Logs` | Объём логов, ERROR и WARN, ошибки по маршрутам, просмотр логов |
| `LoanDebtors Notifications: Traces` | Поток спанов через Collector и Tempo, задержки приёма |
| `LoanDebtors Scheduler: Overview` | Consumer, задания APScheduler, отмена, outbox и последние логи |
| `LoanDebtors Audit Exporter: Overview` | Приём audit-событий, ошибки, DLQ, HTTP и размер страницы журнала |
| `LoanDebtors ABS: Overview` | HTTP-запросы, латентность, ошибки и логи заглушки АБС |
| `LoanDebtors Monitoring: Stack` | Состояние целей Prometheus, Collector и Tempo |

Все дашборды объединены тегом `loandebtors`, поэтому переключаться между ними
можно через меню `Дашборды LoanDebtors` в правом верхнем углу. Правила алертов
Notifications находятся в `source/infra/otel/alerts.yml`, их состояние видно в
Prometheus на странице `Alerts`.

Grafana 11.5 не выполняет TraceQL search в панелях дашборда через backend.
Поэтому отдельные трейсы открываются в Explore с источником Tempo. Дашборд
`Traces` показывает состояние конвейера трейсов, а не список конкретных
трейсов.

Метрики также доступны напрямую в Prometheus: http://localhost:9090.
Коллектор отдаёт метрики в формате Prometheus на
http://localhost:8889/metrics. Если Grafana не нужна, диагностический вывод
телеметрии виден в логах контейнера `otel-collector`.

## Логи

Сервисы пишут структурированные JSON-логи в stdout. Docker сохраняет их, а
OpenTelemetry отправляет те же записи в Collector, Collector передаёт их в Loki.
Loki хранит логи 24 часа в томе `loki-data`. Смотреть логи можно в Grafana:
Explore с источником `Loki` или дашборд `LoanDebtors Notifications: Logs`.

Поля JSON-лога:

- `timestamp`, `level`, `logger`, `message`;
- `service`, `service_version`, `environment`;
- `correlation_id`;
- `trace_id` и `span_id`, если запись сделана внутри спана;
- `event`, `http_method`, `http_route`, `http_status_code`, `duration_ms` для
  access-логов;
- `exception_type` и `exception` при ошибке.

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

Если в строке лога есть `trace_id`, Grafana показывает ссылку `TraceID` на
трейс в Tempo.

Логи в Docker остаются доступны для локальной отладки. Все контейнеры:

```bash
make logs
```

Логи конкретного сервиса или компонента:

```bash
docker compose -f source/infra/compose.yaml logs -f notifications
docker compose -f source/infra/compose.yaml logs -f scheduler
docker compose -f source/infra/compose.yaml logs -f email-channel
docker compose -f source/infra/compose.yaml logs -f audit-exporter
docker compose -f source/infra/compose.yaml logs -f abs
docker compose -f source/infra/compose.yaml logs -f otel-collector
docker compose -f source/infra/compose.yaml logs -f loki
docker compose -f source/infra/compose.yaml logs -f tempo
docker compose -f source/infra/compose.yaml logs -f prometheus
docker compose -f source/infra/compose.yaml logs -f grafana
docker compose -f source/infra/compose.yaml logs -f postgres
docker compose -f source/infra/compose.yaml logs -f rabbitmq
```

Последние 200 строк без режима follow:

```bash
docker compose -f source/infra/compose.yaml logs --tail=200 notifications
```

Поиск по идентификатору корреляции:

```bash
docker compose -f source/infra/compose.yaml logs --since=1h notifications | grep <correlation_id>
```

При локальном запуске `make run-notifications` логи uvicorn и приложения
выводятся в терминал. Для вывода SQL-запросов задайте `DATABASE_ECHO=true`.
Логи миграций Alembic видны в выводе контейнера сервиса при старте.
Коллектор в режиме `debug` пишет сводки по принятым трейсам, метрикам и логам,
а не полные тела телеметрии.

Экспорт логов отключается переменной `OTEL_LOGS_ENABLED=false`. Access-логи
health по умолчанию не пишутся, чтобы не засорять поток; включить их можно
переменной `ACCESS_LOG_HEALTH_ENABLED=true`.

## Сквозные тесты

Сквозные сценарии проверяют цепочку Notifications, Scheduler, ABS, Email Channel,
Mailpit, Audit Exporter и RabbitMQ. Перед запуском стенд должен быть поднят:

```bash
make up-all
make e2e
```

Проверяются немедленный запуск кампании, плановый запуск через Scheduler и
отмена запланированной кампании до срабатывания задания. Тесты создают
уникальные шаблоны и кампании, проверяют письма в Mailpit, статусы кампаний,
audit-события и пустые DLQ. Остановка стенда после прогона:

```bash
make e2e-down
```

Подробности: [source/acceptance](source/acceptance/README.md).

## Технический долг

| ID   | Проблема                                                                                   | Влияние                                                                                                                 |
|------|--------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| H-01 | Отмена выполняющейся кампании не отменяет записи `message.send` в outbox                   | Письма по отменённой кампании продолжают отправляться, результаты игнорируются                                          |
| H-02 | Переходы кампании сохраняются полной перезаписью строки без оптимистической блокировки     | Параллельные `cancel`, `complete`, `start`, `PATCH` и `_fail` могут потерять обновление или оживить отменённую кампанию |
| H-03 | Временные ошибки `campaign.start` обходят `RABBITMQ_RETRY_MAX_ATTEMPTS`                    | При постоянной ошибке АБС сообщение повторяется бесконечно, DLQ и `campaign.failed` не появляются                       |
| H-04 | Исчерпание outbox в Email Channel и Scheduler не переводит запись в терминальное состояние | Результат доставки или `campaign.start` теряется, health остаётся `ok`                                                  |
| H-05 | Email Channel проверяет идемпотентность до SMTP, а отмечает обработку после                | Параллельная доставка одного `message_id` может отправить два письма и получить `IntegrityError` по попытке             |
| H-06 | Scheduler не атомарен в гонке срабатывания и отмены                                        | После отмены может опубликоваться `campaign.start`, а статус `cancelled` перезаписаться                                 |
| H-07 | Разовое задание Scheduler теряется после простоя или остановки процесса                    | One-off остаётся `active` с прошедшим `run_at`, запуск не происходит и не аудируется                                    |
| H-08 | Ошибка восстановления расписаний при старте Scheduler не видна в health и не повторяется   | После восстановления БД задания остаются незарегистрированными до перезапуска                                           |
| H-09 | Self-audit Audit Exporter принимает `correlation_id` из HTTP без ограничения длины         | GET выгрузки журнала возвращает 500 при длинном `X-Request-ID`                                                          |
| H-10 | Сообщения в `queued` без `next_attempt_at` не восстанавливаются                            | При потере результата отправки кампания навсегда остаётся `running`                                                     |

## Команды

```bash
make help          # список целей
make lint          # проверка стиля
make typecheck     # статическая проверка типов
make test          # быстрые тесты без интеграционных
make test-all      # все тесты, включая интеграционные
make test-integration      # интеграционные тесты
make check         # lint + typecheck + test
make contracts     # проверить OpenAPI и AsyncAPI
make e2e           # сквозные тесты на поднятом стенде
make e2e-down      # остановить стенд после e2e
make up            # инфраструктура, Мониторинг и заглушка АБС
make up-all        # поднять инфраструктуру и сервисы в Docker
make smoke         # проверить health Notifications
make smoke-scheduler       # проверить health Scheduler
make smoke-email-channel   # проверить health Email Channel
make smoke-audit-exporter  # проверить health Audit Exporter
make smoke-abs             # проверить health заглушки АБС
make down          # остановить контейнеры
```

Полный список целей и параметров: [Makefile](Makefile).

## Документация

- [Инструкция по использованию системы](QUICKSTART.md)
- [ARC42](docs/arc42/README.md)
- [ADR](docs/adr/README.md)
- [C4](docs/c4/README.md)
- [Контракты](source/contracts/README.md)
- [Инфраструктура](source/infra/README.md)
- [Приемочные E2E-тесты](source/acceptance/README.md)
- [Телеметрия и Мониторинг](docs/arc42/8-cross-cutting-concepts.md), раздел 8.4
