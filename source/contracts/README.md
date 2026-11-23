# Контракты

Подход API-first: контракты создаются до реализации, версионируются и проверяются
контрактными тестами.

| Каталог    | Формат      | Содержимое                                      |
|------------|-------------|-------------------------------------------------|
| `openapi/` | OpenAPI 3.1 | Operator API, Admin Channel API, Audit Export API, Scheduler Health API, ABS Debtor Export API |
| `asyncapi/`| AsyncAPI 3.0| Команды и события RabbitMQ                      |

Контракты:

- `openapi/notifications.yaml` - кампании, шаблоны, запуск и остановка рассылки;
- `openapi/email-channel.yaml` - настройка SMTP-адаптера и email-шаблоны;
- `openapi/audit-exporter.yaml` - read-only выгрузка журнала;
- `openapi/scheduler.yaml` - health Scheduler;
- `openapi/abs.yaml` - контракт внешней АБС для постраничной выгрузки должников;
- `asyncapi/loandebtors.yaml` - `campaign.scheduled`, `campaign.cancelled`,
  `campaign.start`, `message.send`, `message.sent`, `message.failed`,
  `audit.event`.

Контракты являются источником истины для реализации. Изменения проходят ревью
и проверяются контрактными тестами.

## Проверка

```bash
make contracts
```

Цель проверяет AsyncAPI через `asyncapi validate` и каждый OpenAPI-файл через
`uvx openapi-spec-validator`. В CI те же команды выполняет job `contracts`.
