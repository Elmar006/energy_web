# Локальный запуск и проверка

Нужны Docker Compose, Go 1.26, Node 22 и Python 3.12+ для запуска тестов вне контейнеров. Для простого просмотра достаточно Docker Compose.

```bash
docker compose up -d --build
```

Сайт: `http://localhost:53001` (демонстрационный пароль по умолчанию `demo-local-password`). Go API: `http://localhost:58080`; Python engine: `http://localhost:8090`; PostgreSQL: `localhost:55432`. Порты, опубликованные Compose, привязаны к loopback. Redis используется внутри сети Compose. Для не-локального развёртывания задайте длинные случайные `POSTGRES_PASSWORD`, `API_TOKEN`, `APP_DEMO_PASSWORD` в `.env` и поставьте TLS/аутентификацию перед сервисом.

Карта использует **Яндекс Карты JavaScript API 3**. Создайте ключ для пакета «JavaScript API», задайте для него ограничение по HTTP Referer (`localhost` для локального запуска и домен сервиса для развёртывания), затем добавьте `YANDEX_MAPS_API_KEY=...` в корневой `.env` и перезапустите frontend: `docker compose up -d frontend`. Без ключа интерфейс явно показывает состояние «Карта ожидает подключения», а расчёты продолжают работать. Ключ JavaScript API неизбежно передаётся в браузер для загрузки SDK, поэтому ограничение по Referer необходимо. [Официальный быстрый старт Яндекса](https://yandex.ru/maps-api/docs/js-api/common/quickstart.html).

Все данные в `examples/demo.json` синтетические. Публичный Go API требует `Authorization: Bearer <API_TOKEN>` для всех маршрутов кроме `/healthz` и `/readyz`. Его контракт находится в [openapi.json](../openapi.json).

Проверка всего стека:

```bash
python scripts/smoke.py
```

Smoke-тест создаёт тестовые сценарии и задачи в локальной БД, подтверждает идемпотентность запуска, расчёт, симуляцию, объяснения, коридор, парк и вход через production-сборку фронтенда.

Тесты отдельно:

```bash
cd engine && python -m pip install -r requirements.txt && python -m pytest -q
cd backend && TEST_DATABASE_URL='postgres://energy:energy_dev@localhost:55432/energy?sslmode=disable' go test ./...
cd frontend && npm ci && npm run lint && npm run typecheck && npm run build
```

В PowerShell переменная для Go-тестов задаётся через `$env:TEST_DATABASE_URL='postgres://energy:energy_dev@localhost:55432/energy?sslmode=disable'`. БД должна быть запущена перед интеграционными Go-тестами.

Импорт GeoJSON из локального файла:

```bash
cd backend
DATABASE_URL='postgres://energy:energy_dev@localhost:55432/energy?sslmode=disable' \
  go run ./cmd/import-geojson -file /path/data.geojson -name 'Название' \
  -kind observed -source 'URL или описание' -license 'Условия использования'
```

Файл должен быть `FeatureCollection` в WGS84 с корректными координатами. `properties.feature_type` задаёт класс объекта; если его нет, класс будет `unclassified`. Импорт формирует версию набора и SHA-256 исходного файла. Ошибочная геометрия откатывает импорт целиком. Данные читаются через `/api/v1/datasets`, `/api/v1/map?bbox=west,south,east,north` и `/api/v1/tiles/{z}/{x}/{y}`.

`docker compose down` останавливает сервисы, сохраняя volume PostgreSQL. Миграция `001_init.sql` применяется только при первом создании volume; для существующей БД при изменении схемы потребуется отдельный мигратор. Резервное копирование и восстановление для production пока не автоматизированы.
