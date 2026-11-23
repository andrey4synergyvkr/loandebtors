# C4

Диаграммы описаны на PlantUML в формате C4. Исходники лежат в этом каталоге,
готовые SVG находятся в [__assets](__assets/).

## Контекст и контейнеры

| Диаграмма | Исходник | SVG |
|---|---|---|
| Системный контекст | [system-context.puml](system-context.puml) | [system-context.svg](__assets/system-context.svg) |
| Контейнеры | [containers.puml](containers.puml) | [containers.svg](__assets/containers.svg) |

## Сценарии выполнения

| Сценарий | Исходник | SVG |
|---|---|---|
| 6.2. Полная выгрузка должников из АБС | [sequence-campaign-selection.puml](sequence-campaign-selection.puml) | [sequence-campaign-selection.svg](__assets/sequence-campaign-selection.svg) |
| 6.3. Немедленный запуск кампании | [sequence-campaign-start.puml](sequence-campaign-start.puml) | [sequence-campaign-start.svg](__assets/sequence-campaign-start.svg) |
| 6.4. Планирование, срабатывание и отмена | [sequence-scheduling-cancel.puml](sequence-scheduling-cancel.puml) | [sequence-scheduling-cancel.svg](__assets/sequence-scheduling-cancel.svg) |
| 6.5. Доставка письма через Email Channel | [sequence-email-delivery.puml](sequence-email-delivery.puml) | [sequence-email-delivery.svg](__assets/sequence-email-delivery.svg) |
| 6.6. Результат отправки, повтор и завершение | [sequence-message-result.puml](sequence-message-result.puml) | [sequence-message-result.svg](__assets/sequence-message-result.svg) |
| 6.7. Восстановление после сбоя | [sequence-recovery.puml](sequence-recovery.puml) | [sequence-recovery.svg](__assets/sequence-recovery.svg) |
| 6.8. Запись и выгрузка журнала аудита | [sequence-audit.puml](sequence-audit.puml) | [sequence-audit.svg](__assets/sequence-audit.svg) |

`technical-context.puml` является заготовкой и пока не используется в
документации. Текстовое описание сценариев находится в
[6-runtime-view.md](../arc42/6-runtime-view.md).

Скриншоты интерфейсов для [QUICKSTART.md](../../QUICKSTART.md) лежат в
`__assets/quickstart-*.png`.
