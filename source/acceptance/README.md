# Системные E2E-тесты

Каталог содержит сквозные проверки системы на полном Docker-стенде. Тесты
работают как черный ящик: обращаются к публичным HTTP API сервисов, Mailpit и
RabbitMQ Management API. В PostgreSQL и схемы сервисов тесты не ходят.

## Что проверяется

1. Health Notifications, Scheduler, Email Channel, Audit Exporter и ABS.
2. Настройка SMTP-адаптера на Mailpit.
3. Создание email-шаблона и логического шаблона Notifications.
4. Немедленный запуск кампании, выборка должников из ABS, отправка писем,
   публикация результатов и завершение кампании.
5. Плановый запуск кампании через Scheduler.
6. Отмена запланированной кампании до срабатывания задания.
7. Наличие audit-событий `campaign.*`, `message.queued`, `message.sent` в
   Audit Exporter.
8. Пустые DLQ `scheduler.commands`, `email.commands`, `notification.results`,
   `notification.commands` и `audit.events`.

## Запуск

Стенд должен быть поднят и здоров. Из корня репозитория:

```bash
make env
make up-all
```

Или без Makefile:

```bash
docker compose up -d --build
```

Прогон:

```bash
make e2e
```

Остановка стенда:

```bash
make e2e-down
```

`make e2e-down` останавливает весь общий стенд, потому что отдельного профиля
`app` больше нет. `make e2e` запускает только маркер `e2e` с отключённым
`addopts`, поэтому интеграционные тесты в этот прогон не попадают.

## Переменные окружения

| Переменная              | Значение по умолчанию       |
|-------------------------|-----------------------------|
| `NOTIFICATIONS_URL`     | `http://localhost:8001`     |
| `SCHEDULER_URL`         | `http://localhost:8002`     |
| `EMAIL_CHANNEL_URL`     | `http://localhost:8003`     |
| `AUDIT_EXPORTER_URL`    | `http://localhost:8004`     |
| `ABS_URL`               | `http://localhost:9000`     |
| `MAILPIT_URL`           | `http://localhost:8025`     |
| `RABBITMQ_MANAGEMENT_URL` | `http://localhost:15672`  |
| `RABBITMQ_USER`         | `loandebtors`               |
| `RABBITMQ_PASSWORD`     | `loandebtors`               |
| `E2E_TIMEOUT_SECONDS`   | `120`                       |

## Ограничения

- тесты рассчитаны на общий стенд Compose из `source/infra/compose.yaml`,
  который подключается корневым `compose.yaml`;
- в одном прогоне создаются уникальные шаблоны и кампании, но журнал аудита
  append-only, поэтому проверки идут по `campaign_id`, а не по глобальным
  счетчикам;
- сценарии с отказами RabbitMQ, PostgreSQL и перезапусками сервисов в этот
  набор не входят.
