"use client";

import Select from "@/components/ui/select";

import { useState } from "react";
type Audit = {
  scenario_id: string;
  year: number;
  site_id: string;
  served_kwh: number;
  grid_kwh: number;
  pv_used_kwh?: number;
  pv_available_kwh?: number;
  battery_charge_kwh?: number;
  battery_discharge_kwh?: number;
  peak_grid_kw: number;
  peak_station_kw?: number;
  battery_soc_start_kwh?: number;
  battery_soc_end_kwh?: number;
};
const fmt = (value?: number) =>
  value === undefined || value === null
    ? "—"
    : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(
        value,
      );
export default function EnergyAuditDetails({
  rows,
  siteNames,
  truncated,
  scenarioId,
  yearValue,
}: {
  rows: Audit[];
  siteNames: Record<string, string>;
  truncated?: boolean;
  scenarioId?: string;
  yearValue?: number;
}) {
  const [scenario, setScenario] = useState("");
  const [year, setYear] = useState("");
  const scenarios = [...new Set(rows.map((item) => item.scenario_id))];
  const years = [...new Set(rows.map((item) => item.year))].sort(
    (a, b) => a - b,
  );
  const selectedScenario = scenarioId ?? (scenario || scenarios[0]);
  const selectedYear = yearValue !== undefined ? String(yearValue) : year || String(years[0]);
  const filtered = rows.filter(
    (item) =>
      item.scenario_id === selectedScenario &&
      String(item.year) === selectedYear,
  );
  if (!rows.length) return null;
  return (
    <section className="detail-card audit-detail-card">
      <div className="detail-title">
        <h3>Подробный энергетический аудит</h3>
        <span className="small-caption">
          {rows.length} строк{truncated ? " · ответ усечён сервером" : ""}
        </span>
      </div>
      <div className="audit-filters" hidden={scenarioId !== undefined && yearValue !== undefined}>
        <div>
          Сценарий
          <Select
            label="Сценарий"
            value={selectedScenario}
            onValueChange={setScenario}
            options={scenarios.map((item) => ({ value: item, label: item }))}
          />
        </div>
        <div>
          Год
          <Select
            label="Год"
            value={selectedYear}
            onValueChange={setYear}
            options={years.map((item) => ({
              value: String(item),
              label: String(item),
            }))}
          />
        </div>
      </div>
      <div
        className="data-table-scroll"
        role="region"
        tabIndex={0}
        aria-label="Подробные потоки по площадкам"
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Площадка</th>
              <th>Отпущено, кВт·ч</th>
              <th>Из сети, кВт·ч</th>
              <th>PV доступно, кВт·ч</th>
              <th>PV использовано, кВт·ч</th>
              <th>Заряд накопителя, кВт·ч</th>
              <th>Разряд накопителя, кВт·ч</th>
              <th>SoC начало, кВт·ч</th>
              <th>SoC конец, кВт·ч</th>
              <th>Пик сети, кВт</th>
              <th>Пик станции, кВт</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={row.site_id}>
                <th>{siteNames[row.site_id] || row.site_id}</th>
                <td>{fmt(row.served_kwh)}</td>
                <td>{fmt(row.grid_kwh)}</td>
                <td>{fmt(row.pv_available_kwh)}</td>
                <td>{fmt(row.pv_used_kwh)}</td>
                <td>{fmt(row.battery_charge_kwh)}</td>
                <td>{fmt(row.battery_discharge_kwh)}</td>
                <td>{fmt(row.battery_soc_start_kwh)}</td>
                <td>{fmt(row.battery_soc_end_kwh)}</td>
                <td>{fmt(row.peak_grid_kw)}</td>
                <td>{fmt(row.peak_station_kw)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="detail-foot">
        Это аудит ограничений модели по площадкам, году и сценарию. Он не
        включает AC power-flow.
      </p>
    </section>
  );
}
