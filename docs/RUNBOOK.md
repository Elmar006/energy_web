# Локальный запуск и проверка

Нужны Docker Compose, Go 1.26, Node 22 и Python 3.12+ для запуска тестов вне контейнеров. Для простого просмотра достаточно Docker Compose.

```bash
docker compose up -d --build
```

Сайт: `http://localhost:53001` (пароль из `APP_ACCESS_PASSWORD`; значения по умолчанию нет). Go API: `http://localhost:58080`; Python engine: `http://localhost:8090`; PostgreSQL: `localhost:55432`. Порты, опубликованные Compose, привязаны к loopback. Redis используется внутри сети Compose. Для закрытого развёртывания одной организации используйте отдельный `compose.production.yaml`, разные owner/runtime credentials и обязательный HTTPS ingress по [PRODUCTION.md](PRODUCTION.md). Development Compose не является конфигурацией публичного сервиса.

Карта использует **2ГИС MapGL JS API**. Создайте ключ с доступом к Map Tiles API, разрешите домены приложения у поставщика, затем добавьте `DGIS_MAPGL_API_KEY=...` в корневой `.env` и пересоздайте frontend: `docker compose up -d --force-recreate frontend`. Необязательный тёмный стиль из редактора 2ГИС задаётся через `DGIS_MAP_STYLE_ID`. Без ключа интерфейс показывает состояние «Карта ожидает подключения», а расчёты продолжают работать. Веб-ключ передаётся в браузер. [Официальный быстрый старт 2ГИС](https://docs.2gis.com/mapgl/start/first-steps).

Все данные в `examples/demo.json` синтетические. Публичный Go API требует `Authorization: Bearer <API_TOKEN>` для всех маршрутов кроме `/healthz` и `/readyz`. Его контракт находится в [openapi.json](../openapi.json).

Проверка всего стека:

```bash
python scripts/smoke.py
python scripts/smoke_dataset_builder.py
python scripts/smoke_sessions.py
```

Перед запуском экспортируйте `API_TOKEN` и `APP_ACCESS_PASSWORD` из локального `.env` в окружение shell, перед запуском проверок. Первый smoke-тест подтверждает идемпотентность запуска, расчёт, симуляцию, объяснения, коридор, парк и вход через production-сборку фронтенда. Второй загружает четыре синтетических GeoJSON через API, собирает по UUID версий сценарий и доводит его до результата worker. Третий прогоняет CSV сессий через импорт, Go API, worker, оптимизацию, SimPy и отчёт о качестве входов. Все тестовые файлы **синтетические**; проверки создают сценарии и задачи в локальной БД.

Тесты отдельно:

```bash
cd engine && python -m pip install -r requirements-dev.txt && python -m pytest -q
cd backend && TEST_DATABASE_URL='postgres://energy:energy_dev@localhost:55432/energy?sslmode=disable' go test ./...
cd frontend && npm ci && npm run lint && npm run typecheck && npm run build
```

В PowerShell переменная для Go-тестов задаётся через `$env:TEST_DATABASE_URL='postgres://energy:energy_dev@localhost:55432/energy?sslmode=disable'`. БД должна быть запущена перед интеграционными Go-тестами.

Импорт GeoJSON из локального файла:

```bash
cd backend
DATABASE_URL='postgres://energy:energy_dev@localhost:55432/energy?sslmode=disable' \
  go run ./cmd/import-geojson -file /path/data.geojson -name 'Название' \
  -kind observed -source 'URL или описание' -license 'Условия использования' \
  -captured-at '2026-09-24T12:00:00Z'
```

По умолчанию CLI помечает импорт как `assumed`; `observed` указывайте только для заявленной поставщиком наблюдаемой выгрузки. Файл должен быть `FeatureCollection` в WGS84 с корректными координатами. `properties.feature_type` задаёт класс объекта; если его нет, класс будет `unclassified`. Импорт формирует версию набора и SHA-256 исходного файла. Ошибочная геометрия откатывает импорт целиком. Те же данные можно загрузить по `POST /api/v1/datasets/import`, затем выбрать версии и собрать сценарий; схема полей и пример — в [DATASET_SCENARIOS.md](DATASET_SCENARIOS.md). Данные читаются через `/api/v1/datasets`, `/api/v1/map?bbox=west,south,east,north` и `/api/v1/tiles/{z}/{x}/{y}`.

`docker compose down` останавливает сервисы, сохраняя volume PostgreSQL. Одноразовый сервис `migrate` применяет номерные миграции к новой и существующей БД перед запуском API/worker. Для закрытого production-проекта реализован offline backup БД и артефактов с SHA-256 и безопасный `recover-check` в новую БД. Порядок, ограничения и проверенный пример — в [PRODUCTION.md](PRODUCTION.md).
