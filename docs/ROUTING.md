# Дорожная доступность и OSRM

Карта 2ГИС отвечает за отображение. Оптимизатор использует явные связи `travel_edges`: идентификаторы зоны и площадки, дорожное время в минутах. Длительности можно загрузить от выбранного поставщика через JSON или GeoJSON. Зависимости от определённого города нет.

## Опциональный адаптер

`engine/energy/routing.py` получает матрицы OSRM Table API, удаляет недостижимые связи и записывает происхождение, лицензию и SHA-256 ответов. Он запускается отдельно до импорта сценария. Python engine не скачивает дорожный граф при пользовательском расчёте.

Проверки: допустимый HTTP(S)-адрес без credentials/query, форма матрицы, конечные неотрицательные длительности, соответствие waypoint координатам и максимальное удаление от дороги 500 м. `null` означает отсутствие доступного пути; расстояние по прямой вместо него не подставляется. Ответ ограничен 10 МиБ.

## Локальный граф

Поместите выбранный и лицензированный PBF в `data/osrm/region.osm.pbf`. Если источник — OpenStreetMap, сохраняйте ODbL-атрибуцию и SHA-256 исходника. Это условие выбранного набора, а не обязательный источник данных приложения. Команды из корня в PowerShell:

```powershell
$routingVolume = "$($PWD.Path)/data/osrm:/data"
$routingImage = 'ghcr.io/project-osrm/osrm-backend:latest'
docker run --rm -v $routingVolume $routingImage osrm-extract -p /opt/car.lua /data/region.osm.pbf
docker run --rm -v $routingVolume $routingImage osrm-partition /data/region.osrm
docker run --rm -v $routingVolume $routingImage osrm-customize /data/region.osrm
docker compose --profile routing up -d osrm
```

Для воспроизводимого стенда используйте зафиксированный digest образа вместо `latest`, а после замены PBF заново подготовьте и перезапустите граф. В Linux/WSL volume: `"$PWD/data/osrm:/data"`.

```sh
python -m energy.routing \
  --scenario ../data/planning_input.json \
  --output ../data/routing/planning_input.json \
  --osrm-url http://localhost:5000 \
  --routing-dataset '<версия или SHA-256 графа>' \
  --routing-license '<условия источника>'
```

Команда выполняется из `engine/`. Готовый JSON загружается стандартным импортом. OSRM не моделирует наблюдаемую пробку: качество времён зависит от профиля выбранного графа. Ключ MapGL 2ГИС не используется как ключ OSRM или разрешение на API маршрутизации 2ГИС.

[OSRM Table API](https://github.com/Project-OSRM/osrm-backend/blob/master/docs/http.md) · [контракт загрузки](DATA_INGESTION.md).
