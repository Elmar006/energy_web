"use client";

type Obj = Record<string, unknown>;
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
export default function ModelFields({ model, value, onChange }: { model: "corridors/check" | "fleets/schedule"; value: string; onChange: (value: string) => void }) {
  let input: Obj;
  try { input = JSON.parse(value); } catch { return <p className="wb-help">Исправьте JSON, чтобы использовать поля модели.</p>; }
  function field(key: string, label: string, unit?: string) {
    return <label className="wb-field" key={key}><span>{label}{unit ? " · " + unit : ""}</span><input type="number" step="any" value={input[key] === undefined ? "" : String(input[key])} onChange={(event) => { const next = { ...input }; if (event.target.value === "") delete next[key]; else next[key] = Number(event.target.value); onChange(pretty(next)); }} /></label>;
  }
  function array(key: string, label: string, hint: string) {
    return <label className="wb-field" key={key}><span>{label}</span><small>{hint}</small><textarea rows={7} spellCheck={false} defaultValue={pretty(input[key] || [])} onBlur={(event) => { try { const parsed = JSON.parse(event.target.value); if (!Array.isArray(parsed)) throw new Error(); event.target.setCustomValidity(""); onChange(pretty({ ...input, [key]: parsed })); } catch { event.target.setCustomValidity("Нужен JSON-массив"); event.target.reportValidity(); } }} onChange={(event) => event.target.setCustomValidity("")} /></label>;
  }
  return <div className="demand-fields"><h3>{model === "corridors/check" ? "Маршрут и запас энергии" : "Горизонт и назначенные ресурсы"}</h3><div className="wb-fields">{model === "corridors/check" ? <>{field("route_km", "Длина маршрута", "км")}{field("battery_usable_kwh", "Полезная ёмкость", "кВт·ч")}{field("initial_soc", "Начальный SoC", "доля")}{field("reserve_soc", "Резервный SoC", "доля")}{field("consumption_kwh_per_km", "Расход", "кВт·ч/км")}{field("consumption_multiplier", "Сезонный множитель")}</> : <>{field("slot_minutes", "Длительность слота", "мин")}{field("horizon_slots", "Горизонт", "слоты")}{field("efficiency", "КПД зарядки", "доля")}{field("solver_seconds", "Лимит решателя", "сек")}</>}</div>{model === "corridors/check" ? array("stations", "Станции на маршруте", "Массив объектов: id, km, available.") : <div className="wb-model-arrays">{array("buses", "Автобусы", "id, battery_kwh, initial_kwh, minimum_kwh, end_target_kwh.")}{array("sites", "Зарядные площадки", "id, ports, charger_kw, grid_kw.")}{array("trips", "Назначенные рейсы", "id, bus_id, start_slot, end_slot, energy_kwh.")}{array("windows", "Окна зарядки", "bus_id, site_id, start_slot, end_slot; назначения не выводятся из одного GTFS.")}</div>}</div>;
}
