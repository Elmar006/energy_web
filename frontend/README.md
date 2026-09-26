# Веб-интерфейс

Next.js App Router. Сценарии и расчёты проходят через BFF в `src/app/api`; браузер не получает серверный `API_TOKEN`.

## Маршруты

| URL | Экран |
| --- | --- |
| `/login` | Вход в демо-пространство |
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
- `src/lib` — демонстрационный вход, контракты планирования и серверные функции.

Шрифт Onest хранится локально в `public/onest-variable.ttf`; лицензия — `public/ONEST-LICENSE.txt`. Знак приложения — `public/icon.svg`.

## Проверка

```sh
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js src
node node_modules/next/dist/bin/next build
```

Для Playwright: `ENERGY_FRONTEND_URL` задаёт адрес запущенного интерфейса, а `ENERGY_CHROME_PATH` позволяет использовать локальный Chrome.
