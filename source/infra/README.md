# Инфраструктура

Локальный учебный стенд: PostgreSQL, RabbitMQ, Mailpit, OTel Collector,
Loki, Tempo, Prometheus и Grafana. Сервисы собираются общим
[Dockerfile](docker/service.Dockerfile) и входят в тот же Compose-набор.
Общий файл: [source/infra/compose.yaml](compose.yaml). Корневой
[compose.yaml](../../compose.yaml) подключает его через `include`.

## Порты

| Компонент       | Порт             | Назначение                              |
|-----------------|------------------|-----------------------------------------|
| PostgreSQL      | 5432             | Схемы сервисов                          |
| RabbitMQ        | 5672, 15672      | AMQP, веб-консоль                       |
| Mailpit SMTP    | 1025             | Приём писем локально                    |
| Mailpit UI      | 8025             | Просмотр писем                          |
| OTel Collector  | 4317, 4318, 8888, 8889 | OTLP gRPC, OTLP HTTP, внутренние метрики, метрики Prometheus |
| Loki            | 3100             | Приём и хранение логов                  |
| Tempo           | 3200             | HTTP API трейсов                        |
| Prometheus      | 9090             | Метрики и PromQL                        |
| Grafana         | 3000             | Дашборды и Explore                      |
| Notifications   | 8001             | Operator API                            |
| Scheduler       | 8002             | Health                                  |
| Email Channel   | 8003             | Admin Channel API                       |
| Audit Exporter  | 8004             | Audit Export API                        |
| ABS (заглушка)  | 9000             | Постраничная выгрузка должников         |

## Учётные данные и веб-интерфейсы

Учебные значения по умолчанию: пользователь и пароль `loandebtors` для
RabbitMQ, `admin` / `admin` для Grafana. Для изменения параметров скопируйте
`.env.example` в `.env` в корне репозитория. Секреты в репозитории не хранятся.

| Интерфейс             | Адрес                          | Вход                                      |
|-----------------------|--------------------------------|-------------------------------------------|
| Grafana               | http://localhost:3000          | `admin` / `admin`                         |
| Loki                  | http://localhost:3100          | Без входа, отдельного UI нет               |
| Prometheus            | http://localhost:9090          | Без входа                                 |
| Tempo                 | http://localhost:3200          | Без входа, отдельного UI нет               |
| Mailpit               | http://localhost:8025          | Без входа                                 |
| RabbitMQ Management   | http://localhost:15672         | `loandebtors` / `loandebtors`             |
| Notifications Swagger | http://localhost:8001/docs     | Без входа                                 |
| Scheduler Swagger     | http://localhost:8002/docs     | Без входа                                 |
| Email Channel Swagger | http://localhost:8003/docs     | Без входа                                 |
| Audit Exporter Swagger| http://localhost:8004/docs     | Без входа                                 |
| ABS Swagger           | http://localhost:9000/docs     | Без входа                                 |
| OTel Collector        | http://localhost:8889/metrics  | Без входа, отдельного UI нет               |

Grafana использует переменные `GRAFANA_ADMIN_USER` и `GRAFANA_ADMIN_PASSWORD`.
При первом входе может появиться запрос на смену пароля. Если пароль изменён в
UI, используйте новый. Сбросить пароль администратора без удаления данных
можно командой:

```bash
docker exec -it loandebtors-grafana-1 grafana cli admin reset-admin-password admin
```

RabbitMQ использует `RABBITMQ_DEFAULT_USER` и `RABBITMQ_DEFAULT_PASS`.
Контейнер RabbitMQ запускается без persistent volume, поэтому после `make down`
очереди и пользовательские настройки сбрасываются, а учётные данные снова
берутся из `.env`.

Prometheus, Tempo, Mailpit и Swagger-страницы сервисов в учебном стенде
работают без аутентификации. Tempo не имеет полноценного UI: трейсы удобнее
смотреть в Grafana Explore с источником Tempo.

## Запуск

```bash
make up
make up-all
```

`make up` поднимает инфраструктуру, Мониторинг и заглушку АБС, `make up-all`
собирает и запускает инфраструктуру и сервисы. Альтернатива без Makefile:

```bash
# весь стенд из корня репозитория
docker compose up -d --build

# только инфраструктура
docker compose -f source/infra/compose.yaml up -d postgres rabbitmq mailpit otel-collector loki tempo prometheus grafana abs

# весь стенд напрямую из общего файла
docker compose -f source/infra/compose.yaml up -d --build
```

Корневой `compose.yaml` подключает `source/infra/compose.yaml` через `include`,
поэтому оба файла описывают один и тот же набор контейнеров. Отдельного профиля
`app` больше нет: сервисы входят в общий набор и запускаются вместе с
инфраструктурой. Для `include` нужен Docker Compose 2.20 или новее.

Сквозные тесты запускаются на поднятом стенде:

```bash
make e2e
make e2e-down
```

`make e2e` проверяет цепочку Notifications, Scheduler, ABS, Email Channel,
Mailpit, Audit Exporter и RabbitMQ. Подробности в
[source/acceptance](../acceptance/README.md).

Health сервисов проверяет не только приложение, но и зависимости. Notifications
возвращает 200 при доступных PostgreSQL и RabbitMQ, работающих outbox relay,
consumers `campaign.start` и `notification.results` и maintenance worker.
Scheduler проверяет consumer `scheduler.commands`, APScheduler и outbox relay.
Email Channel проверяет outbox relay и consumer `email.commands`. Audit Exporter
проверяет consumer `audit.events`.

## Мониторинг

| Файл                              | Назначение                                      |
|-----------------------------------|-------------------------------------------------|
| `otel/collector.yaml`             | Приём OTLP, экспорт трейсов в Tempo, метрик в Prometheus, логов в Loki, внутренние метрики коллектора |
| `loki/loki.yaml`                  | Хранилище логов, retention 24 часа и правила OTLP-меток |
| `otel/tempo.yaml`                 | Хранилище трейсов                               |
| `otel/prometheus.yml`             | Scrape метрик сервисов, коллектора, Prometheus и Tempo |
| `otel/alerts.yml`                 | Правила алертов Notifications: доступность, DLQ, ошибки outbox, восстановление |
| `grafana/provisioning/`           | Datasource-ы Prometheus, Tempo, Loki и провайдер дашбордов |
| `grafana/dashboards/notifications.json` | Обзор Notifications                    |
| `grafana/dashboards/notifications-http.json` | HTTP-запросы и латентность       |
| `grafana/dashboards/notifications-outbox.json` | Outbox relay и ошибки         |
| `grafana/dashboards/notifications-delivery.json` | Consumer, повторы, DLQ, выборка и восстановление |
| `grafana/dashboards/notifications-logs.json` | Логи, ошибки и поиск по LogQL  |
| `grafana/dashboards/notifications-traces.json` | Конвейер трейсов Collector и Tempo |
| `grafana/dashboards/scheduler.json` | Consumer, задания APScheduler, отмена, outbox и логи Scheduler |
| `grafana/dashboards/audit-exporter.json` | Приём audit-событий, DLQ, HTTP и размер страницы журнала |
| `grafana/dashboards/abs.json` | HTTP-запросы, латентность, ошибки и логи заглушки АБС |
| `grafana/dashboards/monitoring-stack.json` | Состояние стека Мониторинга        |

Поток данных: сервисы отправляют OTLP с трейсами, метриками и логами в
Collector. Collector передаёт трейсы в Tempo, отдаёт метрики Prometheus и
отправляет логи в Loki. Grafana читает все три источника. Collector отдаёт
служебные метрики на порту 8888, Prometheus дополнительно scrape свои метрики
и `/metrics` Tempo. Доступность Collector не входит в health сервисов.

## Логи

Сервисы пишут JSON-логи в stdout. Docker сохраняет их, а OpenTelemetry
отправляет те же записи в Collector, который передаёт их в Loki. Loki хранит
логи 24 часа в томе `loki-data`. Смотреть и искать логи удобнее в Grafana:
Explore с источником Loki или дашборд `LoanDebtors Notifications: Logs`.

| Команда | Назначение |
|---|---|
| `make logs` | Логи всех контейнеров в режиме follow |
| `docker compose -f source/infra/compose.yaml logs -f notifications` | Логи Notifications |
| `docker compose -f source/infra/compose.yaml logs -f abs` | Логи заглушки АБС |
| `docker compose -f source/infra/compose.yaml logs -f otel-collector` | Логи Collector и сводки телеметрии |
| `docker compose -f source/infra/compose.yaml logs -f loki` | Логи Loki |
| `docker compose -f source/infra/compose.yaml logs -f rabbitmq` | Логи брокера |
| `docker compose -f source/infra/compose.yaml logs --tail=200 notifications` | Последние 200 строк |
| `docker compose -f source/infra/compose.yaml logs --since=1h notifications \| grep <correlation_id>` | Поиск по корреляции |

Примеры LogQL:

```logql
{service_name="notifications"}
```

```logql
{service_name="notifications"} | json | level="ERROR"
```

Логи миграций Alembic выводятся при старте контейнера сервиса. Для SQL-логов
задайте `DATABASE_ECHO=true`. Коллектор с `debug` exporter пишет только сводки
по трейсам, метрикам и логам, а не полные тела телеметрии. Экспорт логов
отключается переменной `OTEL_LOGS_ENABLED=false`.

## Схемы PostgreSQL

| Схема           | Владелец        | Содержимое                                      |
|-----------------|-----------------|-------------------------------------------------|
| `notification`  | Notifications   | Outbox, кампании, шаблоны, снимки, сообщения и попытки отправки |
| `scheduler`     | Scheduler       | Расписание, отметки отмены и outbox             |
| `email_channel` | Email Channel   | Настройки канала, шаблоны и отправки            |
| `audit`         | Audit Exporter  | Append-only журнал аудита                       |

Схемы создаются начальными миграциями Alembic. Прямые запросы в чужие схемы
запрещены. Каждый сервис использует собственную таблицу версий Alembic в
`public`: `alembic_version_notifications`, `alembic_version_scheduler`,
`alembic_version_email_channel` и `alembic_version_audit_exporter`. Это
позволяет применять миграции сервисов независимо на общей СУБД.

Заглушка `abs` не владеет схемой PostgreSQL и не имеет миграций: она имитирует
внешнюю систему и хранит данные в JSON-фикстуре внутри пакета.
