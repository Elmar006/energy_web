"use client";

import ObjectTable, { type Column, type RecordRow } from "./ui/object-table";
type Obj = Record<string, unknown>;
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const id: Column = { key: "id", label: "Идентификатор" };
const numeric = (key: string, label: string, optional = false): Column => ({ key, label, type: "number", min: 0, optional });

export default function ModelFields({ model, value, onChange }: { model: "corridors/check" | "fleets/schedule"; value: string; onChange: (value: string) => void }) {
  let input: Obj;
  try { input = JSON.parse(value); if (!input || Array.isArray(input) || typeof input !== "object") throw new Error(); } catch { return <p className="wb-help" role="alert">Исправьте JSON в экспертном режиме, чтобы использовать поля модели.</p>; }
  function field(key: string, label: string, unit?: string, fraction = false) {
    return <label className="wb-field" key={key}><span>{label}{unit ? " · " + unit : ""}</span><input type="number" step="any" min="0" max={fraction ? 100 : undefined} value={input[key] === undefined ? "" : String(Number(input[key]) * (fraction ? 100 : 1))} onChange={event => { const next = { ...input }; if (event.target.value === "") delete next[key]; else next[key] = event.target.valueAsNumber / (fraction ? 100 : 1); onChange(pretty(next)); }} /></label>;
  }
  function table(key: string, label: string, columns: Column[]) {
    return <ObjectTable key={key} label={label} columns={columns} rows={Array.isArray(input[key]) ? input[key] as RecordRow[] : []} onChange={rows => onChange(pretty({ ...input, [key]: rows }))} />;
  }
  const busIds = Array.isArray(input.buses) ? input.buses.map((b: Obj) => String(b.id ?? "")).filter(Boolean) : [];
  const siteIds = Array.isArray(input.sites) ? input.sites.map((s: Obj) => String(s.id ?? "")).filter(Boolean) : [];
  const bus: Column = { key: "bus_id", label: "Машина", options: busIds };
  const start = numeric("start_slot", "Начало, интервал");
  const end = numeric("end_slot", "Конец, интервал");
  return <div className="demand-fields"><h3>{model === "corridors/check" ? "Маршрут и запас энергии" : "Горизонт и назначенные ресурсы"}</h3><div className="wb-fields">{model === "corridors/check" ? <>{field("route_km", "Длина маршрута", "км")}{field("battery_usable_kwh", "Полезная ёмкость", "кВт·ч")}{field("initial_soc", "Начальный заряд", "%", true)}{field("reserve_soc", "Резерв заряда", "%", true)}{field("consumption_kwh_per_km", "Расход", "кВт·ч/км")}{field("consumption_multiplier", "Сезонный множитель")}</> : <>{field("slot_minutes", "Длительность интервала", "мин")}{field("horizon_slots", "Горизонт", "интервалы")}{field("efficiency", "КПД зарядки", "%", true)}{field("solver_seconds", "Лимит решателя", "сек")}</>}</div>
    {model === "corridors/check" ? table("stations", "Станции на маршруте", [id, numeric("km", "Расстояние от начала, км"), { key: "available", label: "Доступна", type: "boolean" }]) : <div className="wb-model-arrays">
      {table("buses", "Автобусы", [id, numeric("battery_kwh", "Батарея, кВт·ч"), numeric("initial_kwh", "Заряд в начале, кВт·ч"), numeric("minimum_kwh", "Минимум, кВт·ч"), numeric("end_target_kwh", "Цель в конце, кВт·ч", true)])}
      {table("sites", "Зарядные площадки", [id, { ...numeric("ports", "Посты"), step: 1 }, numeric("charger_kw", "Пост, кВт"), numeric("grid_kw", "Подключение, кВт")])}
      {table("trips", "Назначенные рейсы", [id, bus, start, end, numeric("energy_kwh", "Расход, кВт·ч")])}
      {table("windows", "Окна зарядки", [bus, { key: "site_id", label: "Площадка", options: siteIds }, start, end])}
    </div>}
  </div>;
}
