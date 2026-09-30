# Веб-интерфейс

Next.js App Router. Сценарии и расчёты проходят через BFF в `src/app/api`; браузер не получает серверный `API_TOKEN`.

Инженерное рабочее пространство: постоянная навигация, общий источник данных, отдельные представления результата и табличные редакторы транспортных моделей. Фактическая поставка, ограничения и проверки описаны в [ENGINEERING_UI_IMPLEMENTATION.md](../docs/frontend/ENGINEERING_UI_IMPLEMENTATION.md).

## Маршруты

| URL | Экран |
| --- | --- |
| `/login` | Вход в рабочее пространство |
| `/plan` | Планирование и карта |
| `/runs/[id]` | Ход расчёта и проверяемый результат |
| `/data/scenario` | Редактор PlanningInput |
| `/data/csv/sessions`, `/data/csv/grid` | Импорт CSV |
| `/data/geo` | GeoJSON и сборка сценария |
| `/data/dated` | Датированный спрос |
| `/mobility` | Спрос из маршрутов |
| `/models/corridor`, `/models/fleet` | Отдельные модели |

Выбранный сохранённый сценарий передаётся между разделами через `?scenario=<uuid>`. Адрес `/runs/[id]` восстанавливает результат после обновления страницы. Форма входа сохраняет исходный адрес в `next` и возвращает пользователя после авторизации.

## Структура

- `src/components/workspace` — состояние рабочего экрана, параметры планирования, результат и типы результата.
- `src/app/layout.tsx` держит `WorkspaceProvider` между маршрутами: переходы через `Link` сохраняют параметры и не запускают проверку сессии заново.
- `src/components/workbench-state.tsx` — состояние и операции редакторов.
- `src/components/workbench-*.tsx` — отдельные формы по источникам данных и моделям.
- `src/components/ui/select.tsx` — доступный стилизованный список вместо нативного `select`.
- `src/components/ui/section-tabs.tsx` — представления расчёта с управлением стрелками, Home и End.
- `src/components/ui/object-table.tsx` — редактирование объектов модели с восстановлением удалённой строки; неизвестные поля контракта сохраняются.
- `src/components/ui/calendar-dates.tsx` — календарные даты и предупреждение о разрывах покрытия.
- `src/components/workspace/territory.tsx` — поиск площадок и инспектор решения, доступные без картографического слоя.
- `src/app/engineering.css` — токены и адаптивная компоновка рабочего пространства поверх общей темы.
- `src/lib` — контракты планирования и серверные функции. Синтетический вход существует только как явно импортируемый пример и fixture в `e2e/fixtures`; runtime не подставляет его.

Шрифт Onest хранится локально в `public/onest-variable.ttf`; лицензия — `public/ONEST-LICENSE.txt`. Знак приложения — `public/icon.svg`.

## Проверка

```sh
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js src
node node_modules/next/dist/bin/next build
```

Для Playwright: `ENERGY_FRONTEND_URL` задаёт адрес запущенного интерфейса, а `ENERGY_CHROME_PATH` позволяет использовать локальный Chrome.

```sh
npm run typecheck
npm run lint
npm run build
APP_ACCESS_PASSWORD='<пароль из .env>' npm run test:e2e -- --workers=2
```

Сквозные тесты требуют запущенных Go API, worker, Python engine и PostgreSQL. Они создают тестовые сценарии и расчёты в локальной БД. Контрактные тесты форм используют подменённые ответы API; тест картографической интеграции использует подменённый SDK 2ГИС и не подтверждает доступность внешних тайлов. Инструкция развёртывания — [START_HERE.md](../START_HERE.md).
