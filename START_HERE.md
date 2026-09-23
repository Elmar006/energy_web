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
| `OSRM_URL` | Адрес дорожного маршрутизатора для CLI-адаптера | При запуске адаптера в сети Compose: `http://osrm:5000`; при запуске на хосте: `http://localhost:5000` |
| `DATABASE_URL`, `ENGINE_URL`, `API_ADDR`, `REDIS_ADDR` | Адреса для запуска сервисов **вне Docker** | В Compose уже заданы внутренние адреса; обычно менять их не нужно |

Ключ Яндекс Карт создайте согласно [официальному быстрому старту](https://yandex.ru/maps-api/docs/js-api/common/quickstart.html). В кабинете ограничьте ключ по HTTP Referer: для локального сайта — используемый `localhost`/`127.0.0.1`, для внешнего — домен приложения. Ключ JavaScript API по своей природе виден в браузере; ограничение по Referer обязательно. Запишите в `.env` строку `YANDEX_MAPS_API_KEY=ваш_ключ` без кавычек.

**Если база уже была создана с другим паролем**, простая смена `POSTGRES_PASSWORD` в `.env` не изменит пароль внутри существующего Docker volume. Верните прежнее значение или явно поменяйте пароль в PostgreSQL. Не удаляйте volume с данными ради «исправления» пароля.

## 3. Запустить

```text
docker compose up -d --build
docker compose ps
```

В `docker compose ps` база и расчётный сервис должны быть `healthy`, остальные сервисы — `Up`. Первый запуск скачивает образы и устанавливает зависимости, поэтому занимает дольше повторных.

Откройте **http://localhost:53001** и войдите паролем `APP_DEMO_PASSWORD` из `.env`. Для встроенного синтетического примера выберите режим, бюджет и уровень спроса, нажмите «Рассчитать план». Результат включает площадки, этапы строительства, покрытие спроса и результаты симуляции.

Для **своего сценария** в блоке «Источник расчёта» загрузите JSON формата `PlanningInput`. Минимальный рабочий пример — [examples/import_sample.json](examples/import_sample.json); он также полностью синтетический и показывает только структуру файла. После проверки JSON сохраняется как неизменяемый снимок в PostgreSQL. Его можно снова выбрать из списка и пересчитать. Карта, названия объектов, годы и расчётный результат берутся из выбранного снимка. Ошибка схемы показывается до запуска worker.

В файле нужно предоставить зоны спроса с 24-часовыми профилями, площадки, варианты зарядок, узлы сети с 24-часовым доступным резервом мощности, сценарии, достижимые связи и экономические параметры. У зон, площадок и узлов укажите `provenance.kind` (`observed`, `derived` или `assumed`) и `provenance.source`. Формальный контракт — [openapi.json](openapi.json), схема `ScenarioSpec`. Пометка `observed` отражает заявление автора файла, а не независимую проверку достоверности платформой. Для полноценного реального расчёта отдельно нужны проверенные наблюдения спроса, условия присоединения от сетевой организации, цены и дорожная доступность; произвольные координаты и данные OSM сами по себе этого не дают.

Для **риска с обоснованными вероятностями** укажите `probability` у каждого сценария; сумма должна быть равна 1. Режим `parameters.risk = "expected_cvar"` максимизирует ожидаемый результат при ограничении верхнего хвоста потерь. Укажите `cvar_alpha` между 0 и 1 и ровно один порог по режиму: `max_cvar_loss_rub` для оператора (убыток NPV ниже нуля, ₽) или `max_cvar_unmet_kwh` для города (необслуженная энергия за модельный горизонт, кВт·ч). Например, `cvar_alpha = 0.9` ограничивает средние потери в худших 10% вероятности по заданным сценариям. Без обоснованных вероятностей оставьте `risk = "worst_case"`; инструмент не выдумывает их из воздуха.

Если есть выгрузка **фактических зарядных сессий**, часовой профиль спроса можно получить воспроизводимым адаптером. CSV содержит `session_id,zone_id,started_at,ended_at,energy_kwh`; даты обязательно с UTC-смещением, `zone_id` должен совпадать с зоной в исходном сценарии. Для проверки формата есть [синтетический CSV](examples/sessions_sample.csv). Пример без локальной установки Python:

```text
docker run --rm -v E:/energy:/workspace -w /workspace/engine energy-engine python -m energy.ingest_sessions --scenario /workspace/examples/import_sample.json --sessions /workspace/examples/sessions_sample.csv --output /workspace/examples/derived_local.json --source "Синтетическая проверка формата" --time-zone Europe/Moscow --start-date 2027-04-01 --end-date 2027-04-01 --kind assumed
```

В WSL замените `E:/energy` на `/mnt/e/energy`. `derived_local.json` можно загрузить на сайте; не добавляйте файл с реальными сессиями в Git. Для подтверждённой выгрузки оператора укажите её источник и `--kind observed`. Без явного выбора адаптер консервативно считает CSV предположением. Он делит кВт·ч между локальными часовыми интервалами пропорционально длительности, усредняет по явно заданному числу дней, сохраняет SHA-256 CSV и происхождение профиля. Пустую зону, повтор `session_id`, невалидную энергию и сессию вне окна он отклоняет. **Это профиль уже отпущенной энергии**, а не доказательство полного потенциального спроса: пользователи, не сумевшие зарядиться, в такой выгрузке отсутствуют.

Если сетевая организация дала почасовой **доступный резерв мощности** для узлов, примените CSV с колонками `grid_node_id,hour,headroom_kw`: ровно 24 строки для каждого узла, часы `0..23`, кВт, без пропусков и повторов. Укажите дату профиля, часовой пояс, источник и условия использования. Адаптер не выводит резерв из одной лишь фоновой нагрузки и не подтверждает заявленные организацией значения. Для проверки формата есть [синтетический CSV](examples/grid_profile_sample.csv); при работе с ним используйте `--kind assumed`, как ниже:

```text
docker run --rm -v E:/energy:/workspace -w /workspace/engine energy-engine python -m energy.ingest_grid --scenario /workspace/examples/import_sample.json --grid /workspace/examples/grid_profile_sample.csv --output /workspace/examples/grid_local.json --source "Синтетическая проверка формата" --profile-date 2026-09-01 --time-zone Europe/Moscow --kind assumed
```

В WSL замените путь монтирования на `/mnt/e/energy:/workspace`. Для полученного от организации профиля укажите его реальный источник, дату и `--kind observed`. Результат — полный новый `PlanningInput` JSON с SHA-256 исходного CSV; его можно загрузить в интерфейсе или передать следующему адаптеру. Один выбранный суточный профиль не доказывает резерв для всех сезонов и лет: для инженерного решения нужны соответствующие временные ограничения и подтверждение присоединения.

### Дорожная матрица из реального OSM-графа

Адаптер OSRM заменяет поле `travel_edges` длительностью поездки по автомобильным дорогам. Источник графа и его SHA-256 записывайте в идентификатор набора; результат также получает SHA-256 ответов маршрутизатора. Недостижимая пара не превращается в расстояние по прямой. Если координата удалена от ближайшей дороги больше чем на 500 м, адаптер останавливается: это часто означает ошибочную территорию или координаты.

Для воспроизводимой локальной проверки можно взять небольшой [экстракт Монако от Geofabrik](https://download.geofabrik.de/europe/monaco.html). Загружайте PBF непосредственно у провайдера; данные OSM распространяются под [ODbL 1.0 с обязательной атрибуцией OpenStreetMap](https://www.geofabrik.de/data/download.html). Здесь только **дороги реальные**. Координаты точек в проверке выбраны вручную, спрос, площадка и мощность остаются синтетическими. Для своего региона замените PBF и все предметные данные на проверенные источники.

PowerShell из корня репозитория:

```powershell
New-Item -ItemType Directory -Force data/osrm | Out-Null
Invoke-WebRequest 'https://download.geofabrik.de/europe/monaco-latest.osm.pbf' -OutFile data/osrm/region.osm.pbf
$graphHash = (Get-FileHash -Algorithm SHA256 data/osrm/region.osm.pbf).Hash.ToLowerInvariant()
docker run --rm -v E:/energy/data/osrm:/data ghcr.io/project-osrm/osrm-backend:latest osrm-extract -p /opt/car.lua /data/region.osm.pbf
docker run --rm -v E:/energy/data/osrm:/data ghcr.io/project-osrm/osrm-backend:latest osrm-partition /data/region.osrm
docker run --rm -v E:/energy/data/osrm:/data ghcr.io/project-osrm/osrm-backend:latest osrm-customize /data/region.osrm
docker compose --profile routing up -d osrm
```

В WSL путь для `-v` замените на `/mnt/e/energy/data/osrm:/data`. После изменения PBF повторите подготовку графа и перезапустите `osrm`. Для проверки возьмите [examples/import_sample.json](examples/import_sample.json), замените координаты **обеих** точек на `zone = (43.7384, 7.4246)` и `site = (43.7340, 7.4290)` (порядок в JSON — `latitude`, `longitude`), оставив происхождение спроса и мощности `assumed`. Например, в PowerShell:

```powershell
$sample = Get-Content examples/import_sample.json -Raw | ConvertFrom-Json
$sample.id = 'mixed-monaco-local'
$sample.zones[0].latitude = 43.7384
$sample.zones[0].longitude = 7.4246
$sample.sites[0].latitude = 43.7340
$sample.sites[0].longitude = 7.4290
$sample | ConvertTo-Json -Depth 100 | Set-Content -Encoding utf8 examples/monaco_input_local.json
```

```powershell
docker run --rm --network energy_default -v E:/energy:/workspace -w /workspace/engine energy-engine python -m energy.routing --scenario /workspace/examples/monaco_input_local.json --output /workspace/examples/monaco_road_local.json --osrm-url http://osrm:5000 --routing-dataset "geofabrik-monaco-pbf-sha256:$graphHash" --routing-license "ODbL 1.0; © OpenStreetMap contributors"
```

В WSL замените путь монтирования на `/mnt/e/energy:/workspace`. Загрузите `examples/monaco_road_local.json` через интерфейс. Он проверится и сохранится в БД, после чего можно запустить расчёт. Для своего региона используйте координаты в пределах загруженного графа; размер области и производительность OSRM подберите под доступную память. [Документация OSRM Table API](https://github.com/Project-OSRM/osrm-backend/blob/master/docs/http.md) описывает используемые матрицы длительностей. Файлы в `data/` и локальные JSON игнорируются Git.

### Электробусы: GTFS и операционные данные

Для расчёта парка загрузите GTFS ZIP от транспортного оператора и укажите дату обслуживания. GTFS даёт времена рейсов и календарь (`trips.txt`, `stop_times.txt`, `calendar.txt`/`calendar_dates.txt`), но **не** даёт энергозатраты машины, фактическое назначение автобуса на рейс и доступность зарядки. Подготовьте отдельный JSON `data/fleet_operations.json` с подтверждёнными или явно сценарными параметрами:

```json
{
  "source": "Диспетчерская выгрузка, дата и владелец",
  "kind": "assumed",
  "time_zone": "Europe/Moscow",
  "slot_minutes": 15,
  "buses": [{"id": "bus-1", "battery_kwh": 300, "initial_kwh": 240, "minimum_kwh": 30}],
  "sites": [{"id": "depot-1", "ports": 4, "charger_kw": 120, "grid_kw": 300}],
  "assignments": [{"trip_id": "ID_РЕЙСА_ИЗ_GTFS", "bus_id": "bus-1", "energy_kwh": 70}],
  "windows": [{"bus_id": "bus-1", "site_id": "depot-1", "start_time": "10:15:00", "end_time": "11:30:00"}]
}
```

Значения выше показывают **формат**, а не данные реального парка. `source` описывает источник назначений и энергии, `kind = "assumed"` остаётся до подтверждения этих данных оператором; `observed` указывайте только для полученной фактической выгрузки. Укажите назначения и окна для нужных рейсов; не назначенные рейсы GTFS в расчёт не входят. Время задаётся в местном времени **дня обслуживания GTFS**: допустимы значения после `24:00:00`. Проверяйте часовой пояс и переходы летнего времени с поставщиком расписания. Чтобы не добавить недоступное время, импортёр округляет занятость рейсом наружу, а окно зарядки внутрь целых слотов. Противоречащие друг другу рейсы и окна отклоняются.

```text
docker run --rm -v E:/energy:/workspace -w /workspace/engine energy-engine python -m energy.ingest_gtfs --gtfs /workspace/data/operator_gtfs.zip --operations /workspace/data/fleet_operations.json --service-date 2027-09-06 --source "Оператор, версия и URL выгрузки" --output /workspace/data/fleet_input.json --manifest /workspace/data/fleet_manifest.json
```

Для WSL замените `E:/energy` на `/mnt/e/energy`. Манифест фиксирует SHA-256 GTFS и параметров оператора, дату и правила округления. `fleet_input.json` имеет контракт `FleetInput`; его можно передать в `POST /api/v1/fleets/schedule` с `Authorization: Bearer <API_TOKEN>` или внутренний `POST /v1/fleet/schedule`. Результат показывает допустимое зарядное расписание либо несовместимость ограничений. Шаблоны рейсов из `frequencies.txt` импортёр явно отклоняет: для них требуется отдельное развёртывание в экземпляры. Текущая модель парка считает энергозатраты рейсов заданными и не строит перегон до зарядки или нелинейную зарядную кривую.

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

Если построен локальный JSON с реальной дорожной матрицей, добавьте к той же команде `-e ENERGY_EXTRA_SCENARIO=/workspace/examples/monaco_road_local.json` **до** имени образа `energy-engine`: smoke-тест дополнительно сохранит, рассчитает и проверит этот сценарий.

Эта Docker-команда приведена для Windows-пути `E:/energy`; в WSL замените путь слева от `:/workspace` на `/mnt/e/energy`. `--env-file .env` передаёт тесту те же локальные значения токена и пароля, что использует Compose.

## 5. Загрузить собственную географию

Импорт принимает GeoJSON `FeatureCollection` в WGS84 (`EPSG:4326`) с ненулевым числом объектов. Геометрия проверяется, импорт транзакционный, версия набора и SHA-256 сохраняются в PostGIS. Укажите настоящие источник и условия использования; `-kind observed` используйте только для наблюдаемых данных.

PowerShell при установленных Go 1.26 и доступной базе:

```powershell
$env:DATABASE_URL = 'postgres://energy:ВАШ_POSTGRES_PASSWORD@localhost:55432/energy?sslmode=disable'
cd backend
go run ./cmd/import-geojson -file 'C:\data\sites.geojson' -name 'Площадки, версия 1' -kind observed -source 'Название и URL исходного набора' -license 'Условия использования'
```

После импорта `GET /api/v1/datasets` показывает версии, `GET /api/v1/map?bbox=west,south,east,north` возвращает объекты, а `GET /api/v1/tiles/{z}/{x}/{y}` — векторные тайлы. Эти маршруты требуют `Authorization: Bearer <API_TOKEN>`; схема публичного API находится в [openapi.json](openapi.json). **На текущем этапе GeoJSON-каталог и расчётные сценарии ещё не связаны автоматически.** Для расчёта подготовьте `PlanningInput` с согласованными идентификаторами, единицами и происхождением данных. Импорт географии **не означает**, что известны свободная мощность подстанции, стоимость присоединения или реальный спрос.

## 6. Остановить и обновить

```text
docker compose down
docker compose up -d --build
```

`down` останавливает сервисы и **сохраняет** PostgreSQL volume. Не добавляйте `-v`, если хотите сохранить сценарии, результаты и загруженные данные. Начальная SQL-схема применяется только при создании нового volume; автоматические миграции существующей базы пока не реализованы. Перед существенным обновлением сохраните резервную копию базы.

Для архитектуры и фактически реализованных возможностей см. [README](README.md), [статус реализации](docs/IMPLEMENTATION_STATUS.md) и [runbook](docs/RUNBOOK.md).
