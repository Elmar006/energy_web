"use client";

type ModelResult = {
  status?: string; diagnostic?: string; reachable?: boolean; farthest_reachable_km?: number;
  legs?: { from: string; to: string; distance_km: number; arrival_soc: number }[];
  station_failure_impacts?: Record<string, { reachable: boolean; replacement_stops: string[] }>;
  peak_kw?: number; schedule?: { bus_id: string; site_id: string; slot: number; kw: number }[];
  trip_ids_served?: string[]; end_energy_kwh?: Record<string, number>; assumptions?: string[];
};
const n = (value: number) => new Intl.NumberFormat("ru", { maximumFractionDigits: 2 }).format(value);
const assumptionLabels: Record<string, string> = {
  "input positions follow a routed corridor": "Расстояния станций заданы вдоль дорожного маршрута.",
  "charging to full at every selected stop": "На каждой выбранной остановке автомобиль заряжается полностью.",
  "constant segment consumption": "Удельный расход постоянен по участкам.",
  "no station queue or opening hours": "Очереди и часы работы станций не учитываются.",
  "fixed trip-to-bus assignment": "Назначения рейсов машинам заданы входными данными.",
  "constant charging power within each slot": "Мощность постоянна внутри временного интервала.",
  "trip energy deducted at departure": "Энергия рейса учитывается при отправлении.",
  "no piecewise charging curve": "Изменение мощности по мере заряда батареи не моделируется.",
};
export default function ModelResultView({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return <p role="alert">Не удалось прочитать результат.</p>;
  const result = value as ModelResult;
  return <section className="model-result" aria-label="Результат модели" aria-live="polite">
    <div className="table-toolbar"><h3>Результат проверки</h3><strong>{result.reachable !== undefined ? result.reachable ? "Маршрут достижим" : "Маршрут недостижим" : result.status === "optimal" ? "Расписание найдено" : result.status === "infeasible" ? "Ограничения несовместимы" : "Расчёт не завершён"}</strong></div>
    {result.diagnostic && <p role="alert">Диагностика: {result.diagnostic}</p>}
    {result.farthest_reachable_km !== undefined && <p>Достижимое расстояние: <strong>{n(result.farthest_reachable_km)} км</strong></p>}
    {result.peak_kw !== undefined && <p>Пиковая мощность: <strong>{n(result.peak_kw)} кВт</strong> · Обеспечено рейсов: {result.trip_ids_served?.length ?? "—"}</p>}
    {Boolean(result.legs?.length) && <div className="data-table-scroll" role="region" aria-label="Участки маршрута" tabIndex={0}><table className="data-table"><thead><tr><th>Откуда</th><th>Куда</th><th>Расстояние, км</th><th>Заряд при прибытии, %</th></tr></thead><tbody>{result.legs?.map((row,i) => <tr key={i}><td>{row.from === "start" ? "Начало маршрута" : row.from}</td><td>{row.to === "destination" ? "Конец маршрута" : row.to}</td><td>{n(row.distance_km)}</td><td>{n(row.arrival_soc * 100)}</td></tr>)}</tbody></table></div>}
    {result.station_failure_impacts && <><h3>Отказ одной станции</h3><div className="data-table-scroll" role="region" aria-label="Отказы станций" tabIndex={0}><table className="data-table"><thead><tr><th>Недоступная станция</th><th>Маршрут</th><th>Остановки замены</th></tr></thead><tbody>{Object.entries(result.station_failure_impacts).map(([station,row]) => <tr key={station}><th scope="row">{station}</th><td>{row.reachable ? "Достижим" : "Недостижим"}</td><td>{row.replacement_stops.join(", ") || "—"}</td></tr>)}</tbody></table></div></>}
    {Boolean(result.schedule?.length) && <><h3>Расписание зарядки</h3><div className="data-table-scroll schedule-scroll" role="region" aria-label="Расписание зарядки" tabIndex={0}><table className="data-table"><thead><tr><th>Машина</th><th>Площадка</th><th>Интервал</th><th>Мощность, кВт</th></tr></thead><tbody>{result.schedule?.map((row,i) => <tr key={i}><th scope="row">{row.bus_id}</th><td>{row.site_id}</td><td>{row.slot}</td><td>{n(row.kw)}</td></tr>)}</tbody></table></div></>}
    {result.end_energy_kwh && <><h3>Заряд в конце горизонта</h3><dl className="audit-metrics">{Object.entries(result.end_energy_kwh).map(([bus,energy]) => <div key={bus}><dt>{bus}</dt><dd>{n(energy)} кВт·ч</dd></div>)}</dl></>}
    {result.assumptions?.length && <div className="wb-note"><div><strong>Границы расчёта</strong><ul>{result.assumptions.map(item => <li key={item}>{assumptionLabels[item] || item}</li>)}</ul></div></div>}
    <details className="wb-advanced"><summary>Технический результат · JSON</summary><pre>{JSON.stringify(value,null,2)}</pre></details>
  </section>;
}
