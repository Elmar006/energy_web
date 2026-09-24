# Прямая загрузка данных и запуск расчёта

Бэкенд принимает исходные CSV через `multipart/form-data`, применяет их к **существующему** сценарию и сохраняет новый неизменяемый снимок. Старый сценарий и его расчёты не меняются. Исходные байты CSV сохраняются в PostgreSQL с SHA-256 и доступны для повторной проверки. Каждый загруженный CSV получает UUID версии; результат оптимизатора и симулятора рассчитывается по новому `scenario.id`.

Требуется запущенный стек из [START_HERE.md](../START_HERE.md). Все `/api/v1/*` запросы требуют `Authorization: Bearer <API_TOKEN>`. Файлы с реальными сессиями и техусловиями не добавляйте в Git. Демонстрационные файлы в `examples/` **синтетические**, поэтому в командах стоит `kind=assumed`.

## Форматы и проверки

| Импорт | Путь после `/api/v1/scenarios/{id}` | CSV | Метаданные | Предел |
|---|---|---|---|---:|
| Выполненные зарядки | `/imports/sessions` | `session_id,zone_id,started_at,ended_at,energy_kwh` | `scenario_name`, `dataset_name`, `source`, `kind`, `time_zone`, `start_date`, `end_date`, опционально `license` | 50 МиБ |
| Резерв узлов подключения | `/imports/grid-headroom` | `grid_node_id,hour,headroom_kw` | `scenario_name`, `dataset_name`, `source`, `kind`, `time_zone`, `profile_date`, опционально `license` | 10 МиБ |

`file` — обязательная часть запроса. `kind` равен `observed` только при настоящей подтверждённой выгрузке; иначе `assumed`. Часовой пояс — IANA, совпадающий с `scenario.spec.time_zone`, если он уже задан. При исходном `null` новый сценарий получает пояс импорта. Даты — `YYYY-MM-DD`. Сессии должны полностью входить в объявленный период, иметь уникальные `session_id`, положительную энергию, временные метки с UTC-смещением и существующий `zone_id`. Для каждого узла сценария нужен ровно один неотрицательный конечный `headroom_kw` на каждый час `0..23`. Неизвестная зона или узел, пропуск часа и пустая зона отклоняются; отсутствующие значения не становятся нулями.

Загрузка сессий пересчитывает `zones[].hourly_kwh`, `mean_session_kwh` и `arrival_profile` из исходных строк; загрузка сети заменяет `grid_nodes[].headroom_kw`. Источник, SHA-256, вид данных, UUID версии и `transform_version` попадают в `spec.datasets[]`; полевая история сохраняется в `provenance`. Версия преобразования участвует в ключе повторной загрузки: новая реализация адаптера не выдаёт прежний снимок за результат обновлённого алгоритма. Для сессий энергия в часовом профиле распределяется равномерно по длительности, поскольку CSV не содержит интервального счётчика. Исторические выполненные сессии **не измеряют скрытый неудовлетворённый спрос**. Профиль резерва — входное ограничение, **не** проверка AC-режима. Подробная интерпретация есть в [REAL_DATA_CALCULATION.md](REAL_DATA_CALCULATION.md).

## Воспроизводимый пример в PowerShell

Из корня `E:\energy` после `docker compose up -d --build`:

```powershell
$apiToken = ((Get-Content .env | Where-Object { $_ -match '^API_TOKEN=' } | Select-Object -First 1) -split '=', 2)[1]
$baseUrl = 'http://localhost:58080'
$headers = @{ Authorization = "Bearer $apiToken" }
$spec = Get-Content examples/import_sample.json -Raw | ConvertFrom-Json
$parent = Invoke-RestMethod -Uri "$baseUrl/api/v1/scenarios" -Method Post -Headers $headers -ContentType 'application/json' -Body (@{ name = 'Synthetic source'; spec = $spec } | ConvertTo-Json -Depth 100)

$session = curl.exe -sS -H "Authorization: Bearer $apiToken" `
  -F 'scenario_name=Synthetic session plan' -F 'dataset_name=Synthetic sessions' `
  -F 'source=repository test fixture' -F 'kind=assumed' -F 'time_zone=Europe/Moscow' `
  -F 'start_date=2027-04-01' -F 'end_date=2027-04-01' `
  -F 'file=@examples/sessions_sample.csv;type=text/csv' `
  "$baseUrl/api/v1/scenarios/$($parent.id)/imports/sessions" | ConvertFrom-Json

$grid = curl.exe -sS -H "Authorization: Bearer $apiToken" `
  -F 'scenario_name=Synthetic sessions and grid' -F 'dataset_name=Synthetic grid reserve' `
  -F 'source=repository test fixture' -F 'kind=assumed' -F 'time_zone=Europe/Moscow' `
  -F 'profile_date=2026-09-01' `
  -F 'file=@examples/grid_profile_sample.csv;type=text/csv' `
  "$baseUrl/api/v1/scenarios/$($session.scenario.id)/imports/grid-headroom" | ConvertFrom-Json

$runHeaders = @{ Authorization = "Bearer $apiToken"; 'Idempotency-Key' = [guid]::NewGuid().ToString() }
$run = Invoke-RestMethod -Uri "$baseUrl/api/v1/scenarios/$($grid.scenario.id)/runs" -Method Post -Headers $runHeaders
do {
  Start-Sleep -Seconds 2
  $state = Invoke-RestMethod -Uri "$baseUrl/api/v1/runs/$($run.id)" -Headers $headers
} while ($state.state -in @('queued', 'running'))
if ($state.state -ne 'succeeded') { throw "Run failed: $($state | ConvertTo-Json -Depth 8)" }
$result = Invoke-RestMethod -Uri "$baseUrl/api/v1/runs/$($run.id)/results" -Headers $headers
$result.optimization.service_by_year
$result.optimization.verification
$result.operational_validation
```

`$session.scenario.id` и `$grid.scenario.id` — новые снимки. `$parent.id` остаётся прежним. Для действительных поставщиков замените CSV, идентификаторы зон/узлов, период, источник и вид данных. Не используйте примерные площадки и тарифы как подтверждённые данные.

В WSL API вызывается теми же `curl -F` полями. Путь к файлу — `@examples/sessions_sample.csv` или `@examples/grid_profile_sample.csv`, адрес — `http://localhost:58080`. Токен берётся из `.env` локально; не вставляйте его в документацию, запросы браузера или Git.

## Проверка источника и ошибок

`POST` возвращает `201` и `{scenario, dataset_id, role, sha256, reused}`. Повтор идентичного файла и метаданных для того же родительского сценария возвращает тот же сценарий с `reused=true`, в том числе при одновременных запросах. Изменение периода, источника или файла создаёт новую версию. `GET /api/v1/datasets` различает записи по `format: "geojson" | "csv"` и даёт `role` для CSV. `GET /api/v1/datasets/{dataset_id}/file` скачивает **точные исходные байты** CSV; заголовок `X-Content-SHA256` позволяет сверить их с ответом и сценарием. Этот путь доступен только с токеном.

`422 invalid_import` означает ошибку CSV, метаданных, часового пояса или несоответствие исходному сценарию; данные при этом не записываются. `404` — отсутствующий родительский сценарий или файл версии. `413` — превышение размера. `503 engine_unavailable` — расчётный сервис недоступен; безопасно повторить запрос. После загрузки обычный `POST /api/v1/scenarios/{new_id}/runs` ставит расчёт в очередь; `GET /api/v1/runs/{run_id}` и `/results` дают статус и результат. Сам факт `201` означает, что вход прошёл валидацию и сохранён, **не** что оптимизатор уже нашёл допустимый план.

Для сквозной автоматической проверки с синтетическими файлами служит `python scripts/smoke_uploaded_data.py` в работающем стеке. Она проверяет воспроизведение исходных байтов, идемпотентность, отказ на неверном узле, неизменность исходного сценария и расчёт worker по двум последовательным импортам.
