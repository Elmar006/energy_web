# Веб-клиент Энергоконтура

Next.js 16 / React 19, App Router. Браузер работает с BFF в `src/app/api`; серверный `API_TOKEN` остаётся в Next.js. Вычисления выполняет Go/Python-контур.

## Разработка

```sh
npm ci
npm run dev
npm test
npm run lint
npm run typecheck
npm run build
```

Для локального Next.js задайте `ENERGY_API_URL=http://localhost:58080`, `APP_ENV=development`, серверный `API_TOKEN`, пароль входа и `SESSION_SECRET`. Docker получает runtime-конфигурацию из корневого `.env`; встроенный dev-сервер обычно работает на 3000, опубликованный Compose — на 53001. Точное назначение переменных и безопасный запуск: [START_HERE.md](../START_HERE.md).

Основной код: `src/components/workspace` — планирование; `workbench-*.tsx` — данные и отдельные модели; `src/components/ui` — доступные элементы; `runtime` — политика сессий/Origin/лимитов. `src/lib/brand.ts` содержит русское название и путь к `public/brand-logo.png`. Шрифты загружаются через next/font/local из `src/app/fonts`, лицензии и SHA находятся рядом.

## Контракты

[Маршруты и состояния интерфейса](../docs/frontend/ENGINEERING_UI_IMPLEMENTATION.md) · [Backend handoff](../docs/frontend/BACKEND_HANDOFF.md) · [Дизайн-система](../docs/frontend/DESIGN_SYSTEM.md) · [OpenAPI](../openapi.json).

Без пользовательского сценария запуск отключён. `examples/demo.json` и `e2e/fixtures` — явные синтетические примеры; runtime не подставляет их. Источник и результат должны совпадать с текущим маршрутом.

## Сквозные тесты

```sh
APP_ACCESS_PASSWORD='<действующий пароль экземпляра>' npm run test:e2e -- --workers=2
```

PowerShell: `$env:APP_ACCESS_PASSWORD='<пароль>'; npm run test:e2e -- --workers=2`. Требуются API, worker, engine и PostGIS. `ENERGY_FRONTEND_URL` задаёт адрес, `ENERGY_CHROME_PATH` позволяет использовать локальный Chrome. Тесты создают данные в локальной БД. Подменённый SDK карты проверяет интеграцию интерфейса, а не внешние тайлы. [Актуальный протокол](../docs/evidence/task-fit-2026-10-01/VERIFICATION.md).
