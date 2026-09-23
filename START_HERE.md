# Запуск «Вектора»: Docker, `.env`, данные и проверка

> **Текущий статус данных.** Встроенный пилот на координатах Екатеринбурга использует **синтетические** спрос, площадки, цены и ограничения мощности. Это проверка работы приложения и алгоритмов, а не готовый инвестиционный расчёт для города. Загрузка собственного GeoJSON уже работает, но сама по себе пока не превращает географические объекты в проверенные данные о спросе и свободной мощности сети. Текущие границы реализации перечислены в [статусе проекта](docs/IMPLEMENTATION_STATUS.md).

## 1. Что нужно установить

- Docker Desktop с Docker Compose v2; на Windows включить движок Linux containers. Для самого запуска Go, Node и Python на компьютере **не нужны**.
- Свободные локальные порты: `53001` (сайт), `58080` (Go API), `8090` (расчётный сервис), `55432` (PostgreSQL).
- Для отображения базовой карты — ключ **JavaScript API 3 Яндекс Карт**. Без ключа расчёты и интерфейс работают, вместо карты показана инструкция подключения.

Команды ниже выполняются из корня этого репозитория: `E:\energy` в PowerShell или `/mnt/e/energy` в WSL. Проверьте, что рядом находятся `compose.yaml`, `backend/`, `engine/` и `frontend/`.

## 2. Создать `.env`

PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
```

Bash/WSL:

```bash
cp .env.example .env
${EDITOR:-nano} .env
```

Замените минимум `POSTGRES_PASSWORD`, `API_TOKEN`, `APP_DEMO_PASSWORD` на свои значения. Для локальной демонстрации допустимы тестовые значения; при доступе извне используйте длинные случайные секреты, TLS и полноценную аутентификацию. Корневой `.env` исключён из Git.

| Переменная | Для чего | Где используется |
|---|---|---|
| `POSTGRES_PASSWORD` | Пароль базы | Compose: PostgreSQL, Go API и worker |
| `API_TOKEN` | Доступ к Go API | Compose: API и Next.js BFF; нужен и для ручных API-запросов |
| `APP_DEMO_PASSWORD` | Пароль входа в веб-демо | Compose: frontend |
| `YANDEX_MAPS_API_KEY` | Публичный ключ JavaScript API 3 | Frontend передаёт его браузеру для загрузки карт|
| `DATABASE_URL`, `ENGINE_URL`, `API_ADDR`, `REDIS_ADDR` | Адреса для запуска сервисов **вне Docker** | В Compose уже заданы внутренние адреса; обычно менять их не нужно |

Ключ Яндекс Карт создайте согласно [официальному быстрому старту](https://yandex.ru/maps-api/docs/js-api/common/quickstart.html). В кабинете ограничьте ключ по HTTP Referer: для локального сайта — используемый `localhost`/`127.0.0.1`, для внешнего — домен приложения. Ключ JavaScript API по своей природе виден в браузере; ограничение по Referer обязательно. Запишите в `.env` строку `YANDEX_MAPS_API_KEY=ваш_ключ` без кавычек.

**Если база уже была создана с другим паролем**, простая смена `POSTGRES_PASSWORD` в `.env` не изменит пароль внутри существующего Docker volume. Верните прежнее значение или явно поменяйте пароль в PostgreSQL. Не удаляйте volume с данными ради «исправления» пароля.

## 3. Запустить

```text
docker compose up -d --build
docker compose ps
```

В `docker compose ps` база и расчётный сервис должны быть `healthy`, остальные сервисы — `Up`. Первый запуск скачивает образы и устанавливает зависимости, поэтому занимает дольше повторных.

Откройте **http://localhost:53001** и войдите паролем `APP_DEMO_PASSWORD` из `.env`. Выберите режим, бюджет и уровень спроса, нажмите «Рассчитать план». Результат включает площадки, этапы строительства, покрытие спроса и результаты симуляции. На пилоте все исходные величины, кроме координатной привязки, являются сценарными предположениями.

Если ключ карты добавлен уже после запуска, примените его без пересборки кода:

```text
docker compose up -d --force-recreate frontend
```

## 4. Проверить работоспособность

PowerShell:

```powershell
Invoke-RestMethod http://localhost:58080/readyz
docker compose logs --tail=100 api worker engine frontend
```

Bash/WSL:

```bash
curl -fsS http://localhost:58080/readyz
docker compose logs --tail=100 api worker engine frontend
```

`readyz` должен вернуть `{"status":"ready"}`. Логи просматривайте локально: не публикуйте их вместе с `.env` или токенами. Если одна служба не стартовала, посмотрите её последние записи через `docker compose logs --tail=100 ИМЯ_СЕРВИСА`.

Для полного интеграционного smoke-теста нужен Python 3 на хосте:

```text
python scripts/smoke.py
```

Он создаёт **тестовые** сценарии и задачи в локальной БД и проверяет API → worker → HiGHS → SimPy → веб-маршруты. При нестандартных `API_TOKEN` и `APP_DEMO_PASSWORD` экспортируйте эти переменные в текущую оболочку перед запуском. Альтернатива без Python на хосте:

```text
docker run --rm --network energy_default --env-file .env -v E:/energy:/workspace -w /workspace -e ENERGY_API_URL=http://api:8080 -e ENERGY_FRONTEND_URL=http://frontend:3000 energy-engine python scripts/smoke.py
```

Эта Docker-команда приведена для Windows-пути `E:/energy`; в WSL замените путь слева от `:/workspace` на `/mnt/e/energy`. `--env-file .env` передаёт тесту те же локальные значения токена и пароля, что использует Compose.

## 5. Загрузить собственную географию

Импорт принимает GeoJSON `FeatureCollection` в WGS84 (`EPSG:4326`) с ненулевым числом объектов. Геометрия проверяется, импорт транзакционный, версия набора и SHA-256 сохраняются в PostGIS. Укажите настоящие источник и условия использования; `-kind observed` используйте только для наблюдаемых данных.

PowerShell при установленных Go 1.26 и доступной базе:

```powershell
$env:DATABASE_URL = 'postgres://energy:ВАШ_POSTGRES_PASSWORD@localhost:55432/energy?sslmode=disable'
cd backend
go run ./cmd/import-geojson -file 'C:\data\sites.geojson' -name 'Площадки, версия 1' -kind observed -source 'Название и URL исходного набора' -license 'Условия использования'
```

После импорта `GET /api/v1/datasets` показывает версии, `GET /api/v1/map?bbox=west,south,east,north` возвращает объекты, а `GET /api/v1/tiles/{z}/{x}/{y}` — векторные тайлы. Эти маршруты требуют `Authorization: Bearer <API_TOKEN>`; схема публичного API находится в [openapi.json](openapi.json). Импорт географии **не означает**, что известны свободная мощность подстанции, стоимость присоединения или реальный спрос. Эти величины должны поступать из отдельных подтверждённых источников и проверяться перед инженерной рекомендацией.

## 6. Остановить и обновить

```text
docker compose down
docker compose up -d --build
```

`down` останавливает сервисы и **сохраняет** PostgreSQL volume. Не добавляйте `-v`, если хотите сохранить сценарии, результаты и загруженные данные. Начальная SQL-схема применяется только при создании нового volume; автоматические миграции существующей базы пока не реализованы. Перед существенным обновлением сохраните резервную копию базы.

Для архитектуры и фактически реализованных возможностей см. [README](README.md), [статус реализации](docs/IMPLEMENTATION_STATUS.md) и [runbook](docs/RUNBOOK.md).
