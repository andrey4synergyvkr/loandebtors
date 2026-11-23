# Architecture Decision Records

Каталог фиксирует архитектурные решения, которые влияют на несколько сервисов
или трудно обратимы. Формат: контекст, решение, последствия. Сводная таблица
находится в [9-architectural-decisions](../arc42/9-architectural-decisions.md).

| ADR | Решение |
|-----|---------|
| [ADR-001](001-transactional-outbox.md) | Транзакционный outbox для исходящих событий |
| [ADR-002](002-unit-of-work.md) | Unit of Work и владение схемой |
| [ADR-003](003-retry-dlq.md) | Retry-очереди и DLQ |
| [ADR-004](004-advisory-lock.md) | Advisory lock и идемпотентный запуск |
| [ADR-005](005-abs-selection.md) | Полная выборка АБС без частичных снимков |
| [ADR-006](006-message-retries.md) | Повторы сообщений и завершение кампании |
| [ADR-007](007-retention-recovery-outbox.md) | Retention, recovery и исчерпание outbox |
| [ADR-008](008-cancellation-tombstone.md) | Отметка отмены кампании в Scheduler |
