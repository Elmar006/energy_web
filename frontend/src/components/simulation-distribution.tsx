"use client";

type Simulation = { scenario_id: string; year: number; seed: number; requested_energy_kwh?: number; energy_kwh?: number; arrivals: number; served_sessions: number; refused_sessions: number; p95_wait_minutes: number | null };
const fmt = (value: number) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value);
function range(values: number[]) { const sorted = [...values].sort((a, b) => a - b); const middle = Math.floor(sorted.length / 2); return { min: sorted[0], median: sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2, max: sorted.at(-1)! }; }

export default function SimulationDistribution({ runs }: { runs: Simulation[] }) {
  const groups = new Map<string, Simulation[]>();
  for (const run of runs) {
    const key = run.scenario_id + " · " + run.year;
    groups.set(key, [...(groups.get(key) || []), run]);
  }
  if (!groups.size) return null;
  return <section className="detail-card sim-distribution"><div className="detail-title"><h3>Разброс по итоговым seed</h3><span className="small-caption">SimPy · одна строка на сценарий и год</span></div><div className="sim-groups">{[...groups.entries()].map(([label, rows]) => {
    const fractions = rows.map((row) => row.requested_energy_kwh ? (row.energy_kwh || 0) / row.requested_energy_kwh * 100 : null).filter((item): item is number => item !== null && Number.isFinite(item));
    const waits = rows.map((row) => row.p95_wait_minutes).filter((item): item is number => item !== null);
    const service = fractions.length ? range(fractions) : null;
    const wait = waits.length ? range(waits) : null;
    return <div className="sim-group" key={label}><div className="sim-title"><strong>{label}</strong><span>{rows.length} seed</span></div>{service ? <><div className="sim-range" role="img" aria-label={"Доля отпущенной энергии от " + fmt(service.min) + " до " + fmt(service.max) + " процентов"}><i style={{ left: Math.max(0, Math.min(100, service.min)) + "%", width: Math.max(1, Math.min(100, service.max) - Math.max(0, service.min)) + "%" }} /><b style={{ left: Math.max(0, Math.min(100, service.median)) + "%" }} /></div><p>Обслуженная энергия: {fmt(service.min)}–{fmt(service.max)}% · медиана {fmt(service.median)}%</p></> : <p>Энергетическая доля недоступна для этого результата.</p>}<p>p95 ожидания: {wait ? fmt(wait.min) + "–" + fmt(wait.max) + " мин · медиана " + fmt(wait.median) + " мин" : "нет завершённых сессий"}</p></div>;
  })}</div><p className="detail-foot">Диапазон показывает случайность сценарной симуляции по seed, а не точность входных данных.</p></section>;
}
