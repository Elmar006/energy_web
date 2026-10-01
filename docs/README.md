# Техническая документация Энергоконтура

Руководства разделены на контракты, работу с данными, эксплуатацию и доказательства. Текущие API/код/миграции имеют приоритет над историческими отчётами. Основные возможности и ограничения собраны в одной [матрице](IMPLEMENTATION_STATUS.md).

## Вход в проект

| Нужно | Читать |
|---|---|
| Запустить и выполнить первый расчёт | [START_HERE.md](../START_HERE.md) |
| Понять поток запроса и границы сервисов | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Проверить фактические возможности | [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) |

## Контракты и данные

| Документ | Назначение |
|---|---|
| [OpenAPI 3.1](../openapi.json) | Генерируемые публичные схемы и маршруты `/api/v1` |
| [RUN_SPEC.md](RUN_SPEC.md) | Версии настроек запуска, хеши, seed и вычислительный бюджет |
| [SERVICE_ACCEPTANCE.md](SERVICE_ACCEPTANCE.md) | Пороги сервиса и accepted/rejected/inconclusive |
| [ALTERNATIVES_MODEL.md](ALTERNATIVES_MODEL.md) | Альтернативы при разных требованиях обслуживания |
| [DIRECT_UPLOAD.md](DIRECT_UPLOAD.md) | Multipart CSV сессий/резерва, исходники и идемпотентность |
| [DATASET_SCENARIOS.md](DATASET_SCENARIOS.md) | Нормализованные GeoJSON-версии и сборка сценария |
| [MOBILITY_DEMAND.md](MOBILITY_DEMAND.md) | Поездки, стоянки, батареи, домашняя зарядка и потенциальные заявки |
| [DATED_DEMAND.md](DATED_DEMAND.md) | ServiceCalendar, ChargingRequest и неизменяемый demand artifact |
| [REAL_DATA_CALCULATION.md](REAL_DATA_CALCULATION.md) | Статистический смысл наблюдений, покрытия и производных профилей |

## Эксплуатация и интерфейс

| Документ | Назначение |
|---|---|
| [RUNBOOK.md](RUNBOOK.md) | Локальная диагностика, проверки, миграции и импорт |
| [PRODUCTION.md](PRODUCTION.md) | Закрытый single-tenant, HTTPS, роли БД, backup/recovery и блокеры |
| [frontend/BACKEND_HANDOFF.md](frontend/BACKEND_HANDOFF.md) | Фактический контракт и обязательные состояния для фронтенда |
| [frontend/ENGINEERING_UI_IMPLEMENTATION.md](frontend/ENGINEERING_UI_IMPLEMENTATION.md) | Маршруты, состояние источника/результата, компоненты и тестирование UI |
| [frontend/DESIGN_SYSTEM.md](frontend/DESIGN_SYSTEM.md) | Токены, типографика, элементы управления и доступность |
| [README веб-клиента](../frontend/README.md) | Структура кода и локальные команды |

## Предметное обоснование и доказательства

| Документ | Назначение |
|---|---|
| [SOLUTION_FOR_ORGANIZERS.md](commission/SOLUTION_FOR_ORGANIZERS.md) | Представление проекта и его способа решения задачи № 03 |
| [TASK_FIT_AUDIT.md](commission/TASK_FIT_AUDIT.md) | Поэлементная сверка исходного PDF с кодом, результатами и пробелами |
| [REPORT.md](commission/REPORT.md) | Методика сравнения, числа, источники, ограничения и повтор запуска |
| [Проверка 1 октября](evidence/task-fit-2026-10-01/VERIFICATION.md) | Текущие тесты, fingerprints и снимки приложения |
| [Закрытое размещение 30 сентября](evidence/production-2026-09-30/VERIFICATION.md) | Исторические проверки ролей, защиты, backup/recovery |
| [Проверка 25 сентября](evidence/VERIFICATION_2026-09-25.md) | Предыдущая версия; не статус текущего кода |

`commission/*.json` и `evidence/**` — неизменяемые результаты и протоколы. Старые промомакеты, повторные планы и визуальные аудиты снятых интерфейсов исключены из действующего комплекта. Фото README имеют [исходник композиции и правила обновления](assets/README.md).

## Правила изменения

1. Публичное поле меняется вместе с OpenAPI, примером и handoff. Совместимость `/api/v1` проверяется тестами.
2. Изменение вычислительных исходников требует нового SHA, заранее закреплённого протокола и нового файла результата. Исторический lock не исправляют под новый код.
3. Execution, solver/verification и service acceptance показываются отдельно. `assumed`, `derived` и `observed` не взаимозаменяемы.
4. Измерение публикуется со входом, версией модели, seed и границами вывода. Случайность симулятора не подменяет достоверность города.
5. Секреты, выгрузки оператора и локальные резервные копии не добавляются в Git. Production-инструкция не обещает возможностей, отсутствующих в матрице.
