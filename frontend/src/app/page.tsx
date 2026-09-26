"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Image from "next/image";
import { Activity, ArrowRight, BatteryCharging, Check, ChevronRight, Clock3, Info, LogOut, MapPinned, ShieldCheck, Zap } from "lucide-react";
import type { Mode } from "@/lib/demo";
import { makeDemo } from "@/lib/demo";
import { isPlanningSpec, provenanceSummary, type PlanningSpec } from "@/lib/planning";
import Workbench from "@/components/workbench";
import ResultInsights from "@/components/result-insights";
import AlternativeDetails from "@/components/alternative-details";
import SimulationDistribution from "@/components/simulation-distribution";
import EnergyAuditDetails from "@/components/energy-audit-details";

const PlanningMap = dynamic(() => import("@/components/planning-map"), { ssr: false, loading: () => <div className="map-loading">Загружаем карту…</div> });

type Selection = { site_id: string; option_id: string; year: number };
type Optimization = {
  status: string;
  objective: number | null;
  gap: number | null;
  selected: Selection[];
  grid_upgrades: { grid_node_id: string; year: number }[];
  battery: { site_id: string; year: number; kwh: number }[];
  solar: { site_id: string; year: number; kw: number }[];
  served_kwh: Record<string, number>;
  unmet_kwh: Record<string, number>;
  cashflow_rub: Record<string, number>;
  diagnostic: string | null;
  risk_metrics?: { cvar_alpha?: number; cvar_loss_rub?: number; cvar_unmet_kwh?: number };
  investment_rub_by_year?: { year: number; rub: number }[];
  service_by_year?: { scenario_id: string; year: number; demand_kwh: number; served_kwh: number; unmet_kwh: number }[];
  energy_audit?: { scenario_id: string; year: number; site_id: string; served_kwh: number; grid_kwh: number; peak_grid_kw: number; peak_station_kw: number; pv_used_kwh?: number; pv_available_kwh?: number; battery_charge_kwh?: number; battery_discharge_kwh?: number; battery_soc_start_kwh?: number; battery_soc_end_kwh?: number }[];
  verification?: { passed?: boolean; max_hourly_energy_balance_error_kwh?: number; max_grid_node_overload_kw?: number; max_budget_overrun_rub?: number; energy_audit_truncated?: boolean };
};
type Simulation = {
  year: number; scenario_id: string; seed: number;
  arrivals: number; served_sessions: number; refused_sessions: number;
  mean_wait_minutes: number | null; p95_wait_minutes: number | null;
  requested_energy_kwh?: number; energy_kwh?: number;
  day_dispatch?: { day_index: number; arrivals: number; queued_sessions_at_boundary: number; dispatch_by_site: { site_id: string; load_kwh: number; grid_kwh: number }[] }[];
};
type Explanation = { site_id: string; status: string; lost_served_kwh: Record<string, number> | null; replacement_sites: string[]; method: string };
type OperationalValidation = { scenario_id: string; year: number; seeds: number; optimized_service_fraction: number; simulated_service_fraction_mean: number; service_gap_percentage_points: number };
type OperationalEconomics = { scenario_id: string; optimized_npv_rub: number; simulated_npv_rub_mean: number; simulated_npv_rub_min: number; simulated_npv_rub_max: number; optimism_gap_rub: number; profitability_sign_changed: boolean };
type Acceptance = { status: string; reason: string; conditions?: { scenario_id: string; year: number; status?: string; metrics?: Record<string, { status?: string; threshold?: number; mean?: number; lower_95?: number; upper_95?: number; reason?: string }> }[] };
type Alternative = { target_service_fraction: number; achieved_min_service_fraction: number | null; same_investment_as_target: number | null; optimization: Optimization; operational_validation?: OperationalValidation[]; operational_economics?: OperationalEconomics[]; service_acceptance?: Acceptance };
type InputQuality = { demand_scope: string; warnings: string[]; observed_session_zone_ids: string[]; parametric_zone_ids: string[]; mobility_derived_zone_ids?: string[]; mobility_sources?: { source: string; source_kind: string; sha256: string }[] };
type Result = { optimization: Optimization; simulation: Simulation[]; explanations?: Explanation[]; alternatives?: Alternative[]; operational_validation?: OperationalValidation[]; operational_economics?: OperationalEconomics[]; service_acceptance?: Acceptance; improvement?: { method?: string; iterations?: { iteration?: number; status?: string; reason?: string; selected_for_holdout?: boolean; added_site_id?: string }[] }; metadata?: { input_quality?: InputQuality; input_sha256?: string; simulation_days?: number } };
type Run = { id: string; scenario_id: string; state: string; error_detail?: string; run_spec?: { schema_version: string; mode: string; simulation_seeds: number[]; development_seeds?: number[]; simulation_days: number; model_version: string }; scenario_sha256?: string; run_spec_sha256?: string; execution_sha256?: string; run_spec_origin?: string };
type SavedScenario = { id: string; name: string; spec: PlanningSpec };
type ScenarioSummary = { id: string; name: string; sha256: string; created_at: string };

const money = (value: number) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value / 1_000_000);
const number = (value: number) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);
const precise = (value: number) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);
const solverStatus = (value: string) => ({ optimal: "Оптимально", feasible: "Допустимо", infeasible: "Невозможно", error: "Ошибка" })[value as "optimal" | "feasible" | "infeasible" | "error"] ?? value;
const inputWarningLabel = (value: string) => ({
  "Observed charging sessions describe fulfilled charging only; latent unmet demand is unknown.": "История зарядок охватывает только выполненные сессии; скрытый неудовлетворённый спрос неизвестен.",
  "The 'observed' source label is supplied by the importer and has not been independently verified.": "Метка «наблюдалось» заявлена при импорте и не проверена независимо.",
  "Session export day-by-day completeness is unverified for some zones; days without records are rejected unless full coverage is explicitly asserted.": "Для части зон полнота выгрузки по дням не подтверждена; пустые дни требуют явного заявления о полном покрытии.",
  "Complete day-by-day session coverage was asserted by the importer, not independently verified.": "Полнота истории по дням заявлена поставщиком, но не проверена независимо.",
  "Hourly charging load was apportioned uniformly across each session duration; interval meter readings were not supplied.": "Почасовая нагрузка распределена по длительности сессий; интервальных показаний счётчика нет.",
  "Some session profiles are declared assumed; their apparent precision does not imply measurement.": "Часть профилей сессий предположена; точные числа не означают, что они измерены.",
  "Zones without session profiles infer arrivals from hourly energy and assumed mean session size.": "В зонах без истории сессий прибытия оценены из почасовой энергии и предполагаемого размера сессии.",
  "At least one session profile has fewer than 7 days or 30 sessions; its temporal and energy distributions are weakly estimated.": "Для части профилей доступно менее 7 дней или 30 сессий; распределения оценены слабо.",
  "At least one grid headroom profile is not labeled observed; connection feasibility remains scenario-based.": "Резерв мощности хотя бы одного узла не подтверждён наблюдениями; подключение остаётся сценарным допущением.",
})[value] ?? value;
const plural = (value: number, one: string, few: string, many: string) => {
  const mod100 = value % 100, mod10 = value % 10;
  return value + " " + (mod100 >= 11 && mod100 <= 14 ? many : mod10 === 1 ? one : mod10 >= 2 && mod10 <= 4 ? few : many);
};

export default function Home() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<Mode>("city");
  const [budget, setBudget] = useState(10);
  const [demand, setDemand] = useState(100);
  const [savedScenarios, setSavedScenarios] = useState<ScenarioSummary[]>([]);
  const [loadedScenario, setLoadedScenario] = useState<SavedScenario | null>(null);
  const [uploading, setUploading] = useState(false);
  const [runId, setRunId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    const previous = new URLSearchParams(window.location.search).get("run");
    return previous && /^[0-9a-f-]{36}$/.test(previous) ? previous : null;
  });
  const [run, setRun] = useState<Run | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [view, setView] = useState<"plan" | "data" | "mobility" | "models">("plan");
  const [runMode, setRunMode] = useState<"default" | "validation" | "improvement">("default");
  const [seedCount, setSeedCount] = useState(30);
  const [simulationDays, setSimulationDays] = useState(3);
  const [minEnergy, setMinEnergy] = useState("");
  const [maxWait, setMaxWait] = useState("");

  useEffect(() => {
    fetch("/api/session").then((r) => r.json()).then((v) => setSignedIn(Boolean(v.signed_in))).catch(() => setSignedIn(false));
  }, []);

  useEffect(() => {
    if (!signedIn) return;
    fetch("/api/scenarios", { cache: "no-store" }).then((response) => response.ok ? response.json() : []).then(setSavedScenarios).catch(() => setSavedScenarios([]));
  }, [signedIn]);

  const demoSpec = useMemo(() => makeDemo(mode, budget * 1_000_000, demand), [mode, budget, demand]);
  const activeSpec: PlanningSpec = loadedScenario?.spec ?? demoSpec;
  const provenance = provenanceSummary(activeSpec);

  const refresh = useCallback(async () => {
    if (!runId || !signedIn) return;
    const response = await fetch(`/api/runs/${runId}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) { setError(payload.error || "Не удалось получить результат"); return; }
    setRun(payload.run);
    if (payload.result) setResult(payload.result);
    if (payload.run.state === "failed") setError(payload.run.error_detail || "Расчёт завершился ошибкой");
  }, [runId, signedIn]);

  useEffect(() => {
    if (!runId || !signedIn || result || run?.state === "failed" || run?.state === "cancelled") return;
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [runId, signedIn, result, run?.state, refresh]);

  useEffect(() => {
    if (!runId || !signedIn || result || run?.state === "failed" || run?.state === "cancelled") return;
    const events = new EventSource("/api/workbench/runs/" + runId + "/events");
    const update = () => void refresh();
    for (const name of ["running", "succeeded", "failed", "cancelled"]) events.addEventListener(name, update);
    events.onmessage = update;
    return () => events.close();
  }, [runId, signedIn, result, run?.state, refresh]);

  useEffect(() => {
    if (!signedIn || !run?.scenario_id || loadedScenario?.id === run.scenario_id) return;
    let cancelled = false;
    fetch(`/api/scenarios/${run.scenario_id}`, { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then((scenario) => {
        if (!cancelled && scenario && isPlanningSpec(scenario.spec)) {
          setLoadedScenario({ id: scenario.id, name: scenario.name, spec: scenario.spec });
        }
      }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [signedIn, run?.scenario_id, loadedScenario?.id]);

  async function login(event: React.FormEvent) {
    event.preventDefault(); setError("");
    const response = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) });
    if (!response.ok) { setError("Неверный пароль доступа"); return; }
    setSignedIn(true); setPassword("");
  }

  async function logout() {
    await fetch("/api/session", { method: "DELETE" });
    setSignedIn(false); setResult(null); setRun(null); setRunId(null); setLoadedScenario(null);
    window.history.replaceState({}, "", "/");
  }

  async function start() {
    setSubmitting(true); setError(""); setResult(null); setRun(null);
    try {
      const requirements = {
        schema_version: "service-v1",
        ...(minEnergy.trim() ? { min_energy_fraction: Number(minEnergy) / 100 } : {}),
        ...(maxWait.trim() ? { max_mean_seed_p95_wait_minutes: Number(maxWait) } : {}),
        min_seeds_per_condition: 30,
      };
      if (runMode !== "default" && (seedCount < 30 || seedCount > 100 || simulationDays < 1 || simulationDays > 14 || (minEnergy && (Number(minEnergy) < 0 || Number(minEnergy) > 100)) || (maxWait && Number(maxWait) < 0))) throw new Error("Проверьте seed, дни и пороги обслуживания");
      if (runMode === "improvement" && !minEnergy.trim() && !maxWait.trim()) throw new Error("Для подбора варианта нужен хотя бы один порог обслуживания");
      const runSpec = runMode === "default" ? undefined : {
        schema_version: runMode === "improvement" ? "run-spec-v2" : "run-spec-v1",
        mode: "validation",
        simulation_seeds: Array.from({ length: seedCount }, (_, index) => index),
        simulation_days: simulationDays,
        ...(minEnergy.trim() || maxWait.trim() ? { service_requirements: requirements } : {}),
        ...(runMode === "improvement" ? { development_seeds: [1001, 1002, 1003], max_improvement_iterations: 3 } : {}),
      };
      const response = await fetch("/api/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...(loadedScenario ? { scenario_id: loadedScenario.id } : { mode, budget: budget * 1_000_000, demand }), ...(runSpec ? { run_spec: runSpec } : {}) }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Не удалось запустить расчёт");
      setRunId(payload.run_id);
      window.history.replaceState({}, "", `?run=${payload.run_id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Ошибка запуска");
    } finally { setSubmitting(false); }
  }

  async function cancelRun() {
    if (!runId) return;
    try {
      const response = await fetch("/api/workbench/runs/" + runId + "/cancel", { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || body.error || "Отмена недоступна");
      await refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось отменить расчёт"); }
  }

  function acceptScenario(scenario: SavedScenario) {
    if (!scenario?.id || !isPlanningSpec(scenario.spec)) throw new Error("Сервис вернул неполный сценарий");
    setLoadedScenario(scenario);
    setSavedScenarios((items) => [{ id: scenario.id, name: scenario.name, sha256: "", created_at: new Date().toISOString() }, ...items.filter((item) => item.id !== scenario.id)]);
    setRunId(null); setRun(null); setResult(null); setError("");
    window.history.replaceState({}, "", "/");
  }

  async function chooseScenario(id: string) {
    setError("");
    setView("plan");
    if (!id) {
      setLoadedScenario(null); setRunId(null); setRun(null); setResult(null);
      window.history.replaceState({}, "", "/");
      return;
    }
    try {
      const response = await fetch(`/api/scenarios/${id}`, { cache: "no-store" });
      const scenario = await response.json();
      if (!response.ok || !isPlanningSpec(scenario.spec)) throw new Error("Сохранённый сценарий повреждён или недоступен");
      setLoadedScenario({ id: scenario.id, name: scenario.name, spec: scenario.spec });
      setRunId(null); setRun(null); setResult(null);
      window.history.replaceState({}, "", "/");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось открыть сценарий"); }
  }

  async function uploadScenario(file: File) {
    setError(""); setUploading(true);
    setView("plan");
    try {
      if (file.size > 2_000_000) throw new Error("Файл больше 2 МБ");
      const parsed = JSON.parse(await file.text());
      const spec = parsed?.spec ?? parsed;
      const name = typeof parsed?.name === "string" ? parsed.name : file.name.replace(/\.json$/i, "");
      const response = await fetch("/api/scenarios", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, spec }),
      });
      const scenario = await response.json();
      if (!response.ok) throw new Error(scenario.error || "Сценарий не прошёл проверку");
      if (!isPlanningSpec(scenario.spec)) throw new Error("Сохранённый сценарий не удалось прочитать");
      setLoadedScenario({ id: scenario.id, name: scenario.name, spec: scenario.spec });
      setSavedScenarios((items) => [{ id: scenario.id, name: scenario.name, sha256: scenario.sha256, created_at: new Date().toISOString() }, ...items]);
      setRunId(null); setRun(null); setResult(null);
      window.history.replaceState({}, "", "/");
    } catch (caught) {
      setError(caught instanceof SyntaxError ? "Файл должен содержать корректный JSON" : caught instanceof Error ? caught.message : "Ошибка загрузки");
    } finally { setUploading(false); }
  }

  if (signedIn === null) return <main className="screen-centered"><p>Загружаем рабочее пространство…</p></main>;
  if (!signedIn) return (
    <main className="screen-centered"><div className="login-panel">
      <div className="brand-mark"><Image src="/brand-logo.png" width={48} height={48} alt="" /></div>
      <p className="eyebrow">Платформа планирования</p>
      <h1>EV Infrastructure</h1>
      <p>Инженерные решения для зарядной сети, проверенные моделированием.</p>
      <form onSubmit={login}>
        <label htmlFor="password">Пароль доступа</label>
        <input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-invalid={Boolean(error)} aria-describedby={error ? "password-error" : undefined} required />
        <button className="primary-button" type="submit">Открыть рабочее пространство <ArrowRight size={17} /></button>
      </form>
      {error && <p id="password-error" className="error-banner" role="alert">{error}</p>}
    </div></main>
  );

  const plan = result?.optimization;
  const primaryScenario = activeSpec.scenarios[0]?.id ?? "базовый";
  const firstYear = activeSpec.parameters.years[0] ?? 2027;
  const yearsLabel = activeSpec.parameters.years.length > 1 ? `${firstYear}–${activeSpec.parameters.years.at(-1)}` : String(firstYear);
  const base = plan?.served_kwh[primaryScenario] || 0;
  const unmet = plan?.unmet_kwh[primaryScenario] || 0;
  const rate = base + unmet > 0 ? Math.round(base / (base + unmet) * 100) : 0;
  const simulations = result?.simulation.filter((s) => s.scenario_id === primaryScenario && s.year === firstYear) || [];
  const measuredWaits = simulations.map((sample) => sample.p95_wait_minutes).filter((value): value is number => value !== null && value !== undefined);
  const avgWait = measuredWaits.length ? measuredWaits.reduce((total, value) => total + value, 0) / measuredWaits.length : null;
  const scenarios = plan ? Object.keys(plan.served_kwh) : [];
  const comparison = plan ? [{ name: "Основной план", optimization: plan, validation: result?.operational_validation, economics: result?.operational_economics, acceptance: result?.service_acceptance },
    ...(result?.alternatives || []).map((alternative) => ({
      name: `Порог ${Math.round(alternative.target_service_fraction * 100)}%`,
      optimization: alternative.optimization, validation: alternative.operational_validation, economics: alternative.operational_economics, acceptance: alternative.service_acceptance,
    }))] : [];
  const operationalRuns = simulations.filter((run) => run.day_dispatch?.length);
  const dayCount = Math.max(0, ...operationalRuns.map((run) => run.day_dispatch?.length || 0));
  const dayRows = Array.from({ length: dayCount }, (_, day) => {
    const rows = operationalRuns.map((run) => run.day_dispatch?.[day]).filter((row) => row !== undefined);
    const divisor = rows.length || 1;
    return { day: day + 1, arrivals: rows.reduce((sum, row) => sum + row.arrivals, 0) / divisor,
      delivered: rows.reduce((sum, row) => sum + row.dispatch_by_site.reduce((total, site) => total + site.load_kwh, 0), 0) / divisor,
      grid: rows.reduce((sum, row) => sum + row.dispatch_by_site.reduce((total, site) => total + site.grid_kwh, 0), 0) / divisor,
      queue: rows.reduce((sum, row) => sum + row.queued_sessions_at_boundary, 0) / divisor };
  });
  const auditRows = plan?.energy_audit?.filter((row) => row.scenario_id === primaryScenario && row.year === firstYear) || [];

  return <div className="app-shell">
    <header className="app-header">
      <div className="brand"><span className="brand-mark small"><Image src="/brand-logo.png" width={34} height={34} alt="" /></span><strong>EV Infrastructure</strong><span className="brand-divider" /><span className="brand-caption">Планирование инфраструктуры</span></div>
      <div className="header-status"><span className="status-pulse" aria-hidden="true" /><span className="header-status-label">Демо-доступ</span><button type="button" className="logout-button" onClick={logout} aria-label="Выйти из рабочего пространства" title="Выйти"><LogOut size={16} /></button></div>
    </header>
    <nav className="app-nav" aria-label="Разделы рабочего пространства">{([["plan", "Планирование"], ["data", "Данные и версии"], ["mobility", "Маршруты"], ["models", "Отдельные модели"]] as const).map(([id, label]) => <button key={id} type="button" className={view === id ? "active" : ""} aria-current={view === id ? "page" : undefined} onClick={() => setView(id)}>{label}</button>)}</nav>

    <main className="workspace">
      <section className="page-intro" aria-labelledby="page-title">
        <div><p className="eyebrow"><MapPinned size={14} /> ПРОЕКТ / СЦЕНАРНОЕ ПЛАНИРОВАНИЕ</p><h1 id="page-title">Развитие зарядной сети</h1><p>Выберите условия и получите план размещения с проверкой энергосети и спроса.</p></div>
        <div className="intro-note"><ShieldCheck size={19} /><span>{loadedScenario ? "Загруженный сценарий" : "Пилотный сценарий"}<br /><strong>{loadedScenario ? loadedScenario.name : "Екатеринбург · синтетические данные"}</strong></span></div>
      </section>

      <div className="workspace-grid">
        <aside className="control-panel" aria-labelledby="scenario-title">
          <div className="panel-heading"><span className="panel-icon"><Activity size={18} /></span><div><p className="eyebrow">ПАРАМЕТРЫ РАСЧЁТА</p><h2 id="scenario-title">Новый сценарий</h2></div></div>
          <div className="scenario-source"><label htmlFor="saved-scenario">Источник расчёта</label><select id="saved-scenario" value={loadedScenario?.id ?? ""} onChange={(event) => void chooseScenario(event.target.value)}><option value="">Демо · синтетические данные</option>{savedScenarios.filter((item) => !item.name.startsWith("Демо ·")).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><label className="file-label" htmlFor="scenario-file">Загрузить PlanningInput JSON</label><input id="scenario-file" className="file-input" type="file" accept=".json,application/json" disabled={uploading} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadScenario(file); event.currentTarget.value = ""; }} /><small>{uploading ? "Проверяем и сохраняем…" : "Площадки, спрос, сеть, тарифы и происхождение данных проверяются перед сохранением."}</small></div>
          {loadedScenario && <div className="source-quality"><strong>Качество входа</strong><span>Записи спроса, площадок и узлов: {provenance.observed} наблюдаемых · {provenance.derived} вычисленных · {provenance.assumed} предположенных.</span>{activeSpec.datasets?.length ? <ul>{activeSpec.datasets.map((dataset) => <li key={dataset.sha256}><strong>{dataset.name} · {dataset.kind}</strong><span>{dataset.source}</span><code>SHA-256 {dataset.sha256.slice(0, 12)}…</code></li>)}</ul> : <span>Манифест исходных файлов не указан. Смотрите происхождение у объектов в JSON.</span>}</div>}
          {!loadedScenario && <>
          <fieldset className="mode-options"><legend>Цель планирования</legend>
            <label className={`mode-card ${mode === "city" ? "active" : ""}`}><input type="radio" name="mode" checked={mode === "city"} onChange={() => setMode("city")} /><span className="mode-text"><strong>Для города</strong><small>Максимальная доступность зарядки</small></span><span className="mode-check">{mode === "city" && <Check size={15} />}</span></label>
            <label className={`mode-card ${mode === "operator" ? "active" : ""}`}><input type="radio" name="mode" checked={mode === "operator"} onChange={() => setMode("operator")} /><span className="mode-text"><strong>Для оператора</strong><small>Экономика развития сети</small></span><span className="mode-check">{mode === "operator" && <Check size={15} />}</span></label>
          </fieldset>
          <div className="field-block"><label htmlFor="budget">Инвестиционный бюджет <strong>{budget} млн ₽</strong></label><input id="budget" type="range" min="1" max="50" step="1" value={budget} onChange={(e) => setBudget(Number(e.target.value))} /><div className="range-ends"><span>1 млн ₽</span><span>50 млн ₽</span></div></div>
          <div className="field-block"><label htmlFor="demand">Уровень спроса <strong>{demand}%</strong></label><input id="demand" type="range" min="50" max="200" step="10" value={demand} onChange={(e) => setDemand(Number(e.target.value))} /><div className="range-ends"><span>50%</span><span>200%</span></div></div>
          </>}
          <div className="parameters-summary"><div><Clock3 size={17} /><span>Горизонт</span><strong>{yearsLabel}</strong></div><div><Zap size={17} /><span>Энергосеть</span><strong>{plural(activeSpec.grid_nodes.length, "узел", "узла", "узлов")}</strong></div><div><MapPinned size={17} /><span>Площадки</span><strong>{plural(activeSpec.sites.length, "кандидат", "кандидата", "кандидатов")}</strong></div></div>
          <details className="run-settings"><summary>Настройки проверки расчёта</summary><label>Режим<select value={runMode} onChange={(event) => setRunMode(event.target.value as typeof runMode)}><option value="default">Базовый · 3 seed</option><option value="validation">Итоговая проверка</option><option value="improvement">Подбор + итоговая проверка</option></select></label>{runMode !== "default" && <><label>Итоговые seed · 30–100<input type="number" min={30} max={100} value={seedCount} onChange={(event) => setSeedCount(Number(event.target.value))} /></label><label>Длительность · дни<input type="number" min={1} max={14} value={simulationDays} onChange={(event) => setSimulationDays(Number(event.target.value))} /></label><label>Мин. обслуженной энергии · %<input type="number" min={0} max={100} step={1} value={minEnergy} onChange={(event) => setMinEnergy(event.target.value)} placeholder="Без порога" /></label><label>Макс. p95 ожидания · мин<input type="number" min={0} value={maxWait} onChange={(event) => setMaxWait(event.target.value)} placeholder="Без порога" /></label><small>{runMode === "improvement" ? "Подбор ведётся на seed 1001–1003; итоговая приёмка — на отдельном потоке." : "Порог проверяется по каждому году и сценарию в SimPy."}</small></>}</details>
          <button className="primary-button run-button" onClick={start} disabled={submitting || (runId !== null && run?.state !== "succeeded" && run?.state !== "failed" && run?.state !== "cancelled")}>
            {submitting ? "Запускаем…" : runId && !result && run?.state !== "failed" ? "Идёт расчёт…" : "Рассчитать план"}<ArrowRight size={18} />
          </button>
          <p className="panel-disclaimer"><Info size={15} /> {loadedScenario ? "Происхождение записей задаётся автором файла; техническая проверка формата не подтверждает достоверность исходных данных." : "Все мощности, цены и спрос в пилоте — сценарные предположения."} Результат не является согласованием подключения.</p>
        </aside>

        <div className="main-column">
          {view !== "plan" && <Workbench key={view} view={view} spec={activeSpec} scenario={loadedScenario} onSaved={acceptScenario} />}
          <div className="planning-content" hidden={view !== "plan"}>
          <section className="map-panel" aria-labelledby="map-title"><div className="section-head"><div><p className="eyebrow">ПРОСТРАНСТВЕННАЯ МОДЕЛЬ</p><h2 id="map-title">Площадки и зоны спроса</h2></div><span className="section-meta">{plural(activeSpec.sites.length, "площадка", "площадки", "площадок")} · {plural(activeSpec.grid_nodes.length, "узел", "узла", "узлов")} сети</span></div><PlanningMap sites={activeSpec.sites} zones={activeSpec.zones} selected={plan?.selected} /></section>

          {error && <div className="error-banner" role="alert">{error}</div>}
          {runId && !result && run?.state !== "failed" && run?.state !== "cancelled" && <section className="calculating" role="status" aria-live="polite"><span className="loading-orbit" /><div><strong>Рассчитываем инфраструктуру</strong><p>Проверяем бюджет, энергосеть и работу станций. Состояние: {run?.state === "running" ? "выполняется" : "в очереди"}.</p></div><button className="secondary-button" onClick={() => void cancelRun()}>Отменить</button></section>}
          {run?.state === "cancelled" && <section className="empty-result"><span className="empty-icon"><Info size={24} /></span><div><h2>Расчёт отменён</h2><p>Можно изменить настройки и запустить новый расчёт.</p></div></section>}

          {plan && plan.status !== "optimal" && plan.status !== "feasible" ? <section className="empty-result" role="alert"><span className="empty-icon"><Info size={24} /></span><div><h2>{plan.status === "infeasible" ? "Ограничения несовместимы" : "Не удалось получить план"}</h2><p>{plan.diagnostic || "Проверьте исходные данные и ограничения сценария."}</p></div></section> : plan ? <section className="results" aria-labelledby="results-title" aria-live="polite">
            <div className="results-heading"><div><p className="eyebrow">РЕЗУЛЬТАТ / {plan.status === "optimal" ? "ОПТИМАЛЬНОЕ РЕШЕНИЕ" : "ДОПУСТИМОЕ РЕШЕНИЕ"}</p><h2 id="results-title">План развития сети</h2></div><span className="result-badge"><Check size={15} /> Расчёт завершён</span></div>
            <div className="metric-grid">
              <div className="metric-card"><span>Обслуженный спрос</span><strong>{rate}%</strong><small>Базовый сценарий · суммарно</small></div>
              <div className="metric-card"><span>Выбранные площадки</span><strong>{plan.selected.length}</strong><small>Строительство в {yearsLabel}</small></div>
              <div className="metric-card"><span>NPV · {primaryScenario}</span><strong>{money(plan.cashflow_rub[primaryScenario] || 0)} <em>млн ₽</em></strong><small>По заданным тарифам и затратам</small></div>
              <div className="metric-card"><span>p95 ожидания</span><strong>{avgWait === null ? "—" : `${Math.round(avgWait)} мин`}</strong><small>Симуляция · {firstYear} · {simulations.length} seed</small></div>
            </div>
            <ResultInsights result={result!} run={run} />
            <SimulationDistribution runs={result?.simulation || []} />
            <EnergyAuditDetails rows={plan.energy_audit || []} siteNames={Object.fromEntries(activeSpec.sites.map((site) => [site.id, site.name]))} truncated={plan.verification?.energy_audit_truncated} />
            <div className="result-lower">
              <div className="detail-card"><div className="detail-title"><h3>Этапы строительства</h3><ChevronRight size={18} /></div>
                <ul className="station-list">{plan.selected.map((entry) => {
                  const site = activeSpec.sites.find((s) => s.id === entry.site_id);
                  return <li key={entry.site_id}><span className="station-indicator" /><div><strong>{site?.name || entry.site_id}</strong><small>{entry.option_id.toUpperCase()} · ввод {entry.year}</small></div><span className="year-pill">{entry.year}</span></li>;
                })}</ul>
                {plan.selected.length === 0 && <p className="detail-foot"><Info size={16} /> {activeSpec.parameters.mode === "operator" ? "При заданных условиях строительство не улучшает экономический результат." : "При заданных ограничениях новые площадки не выбраны."}</p>}
                {plan.grid_upgrades.length > 0 && <p className="detail-foot"><Zap size={16} /> Усиление сети: {plan.grid_upgrades.map((x) => x.grid_node_id).join(", ")}</p>}
                {plan.solar.length > 0 && <p className="detail-foot"><BatteryCharging size={16} /> Локальная генерация: {plan.solar.map((x) => `${x.site_id} ${x.kw} кВт`).join(", ")}</p>}
              </div>
              <div className="detail-card"><div className="detail-title"><h3>Устойчивость к росту спроса</h3><span className="small-caption">кВт·ч за период</span></div>
                <div className="scenario-bars">{scenarios.map((key) => {
                  const used = plan.served_kwh[key] || 0, missed = plan.unmet_kwh[key] || 0;
                  const percent = used + missed ? used / (used + missed) * 100 : 0;
                  return <div key={key} className="scenario-row"><div><strong>{key}</strong><span>{Math.round(percent)}% покрыто</span></div><div className="bar-track" role="img" aria-label={`${key}: обслужено ${number(used)} киловатт-часов из ${number(used + missed)}`}><span style={{ width: `${percent}%` }} /></div><small>{number(used)} / {number(used + missed)} кВт·ч</small></div>;
                })}</div>
                {plan.risk_metrics?.cvar_alpha !== undefined && (plan.risk_metrics.cvar_loss_rub !== undefined || plan.risk_metrics.cvar_unmet_kwh !== undefined) &&
                  <div className="risk-metric"><span>CVaR · худшие {precise((1 - plan.risk_metrics.cvar_alpha) * 100)}% вероятности</span><strong>{plan.risk_metrics.cvar_loss_rub !== undefined ? `${precise(plan.risk_metrics.cvar_loss_rub)} ₽` : `${precise(plan.risk_metrics.cvar_unmet_kwh ?? 0)} кВт·ч`}</strong><small>Допустимый предел: {plan.risk_metrics.cvar_loss_rub !== undefined ? `${precise(activeSpec.parameters.max_cvar_loss_rub ?? 0)} ₽ убытка NPV` : `${precise(activeSpec.parameters.max_cvar_unmet_kwh ?? 0)} кВт·ч необслуженного спроса`}. Среднее по худшему хвосту заданных сценариев.</small></div>}
                <p className="detail-foot"><Info size={16} /> При изменении предположений план нужно пересчитать.</p>
              </div>
            </div>
            {Boolean(result?.explanations?.length) && <div className="detail-card explanation-card"><div className="detail-title"><h3>Почему выбраны площадки</h3><span className="small-caption">пересчёт без объекта</span></div>
              <div className="explanation-list">{result?.explanations?.map((item) => {
                const site = activeSpec.sites.find((entry) => entry.id === item.site_id);
                const lost = item.lost_served_kwh?.[primaryScenario];
                return <div className="explanation-row" key={item.site_id}><strong>{site?.name || item.site_id}</strong><span>{item.status === "fixed" ? "Объект закреплён" : lost === undefined ? "Альтернатива не найдена" : lost > 0 ? `Без объекта: −${number(lost)} кВт·ч обслуживания` : "Спрос может покрыть другая площадка"}</span></div>;
              })}</div>
              <p className="detail-foot"><Info size={16} /> Эффект рассчитан повторной оптимизацией с исключением площадки.</p>
            </div>}
            <div className="defense-grid">
              <section className="detail-card defense-card" aria-labelledby="alternatives-title"><div className="detail-title"><h3 id="alternatives-title">Основной план и альтернативы</h3><span className="small-caption">один вход · {primaryScenario} · {firstYear}</span></div>
                <div className="data-table-scroll" role="region" tabIndex={0} aria-label="Сравнение планов"><table className="data-table"><thead><tr><th scope="col">План</th><th scope="col">CAPEX всего</th><th scope="col">SimPy</th><th scope="col">Разрыв</th><th scope="col">Статус</th></tr></thead><tbody>{comparison.map((row) => {
                  const validation = row.validation?.find((item) => item.scenario_id === primaryScenario && item.year === firstYear);
                  const capex = row.optimization.investment_rub_by_year?.reduce((sum, item) => sum + item.rub, 0) ?? null;
                  return <tr key={row.name}><th scope="row">{row.name}</th><td>{capex === null ? "—" : `${money(capex)} млн ₽`}</td><td>{validation ? `${precise(validation.simulated_service_fraction_mean * 100)}%` : "—"}</td><td>{validation ? `${precise(validation.service_gap_percentage_points)} п.п.` : "—"}</td><td>{solverStatus(row.optimization.status)}</td></tr>;
                })}</tbody></table></div>
                <AlternativeDetails alternatives={result?.alternatives || []} />
                <p className="detail-foot"><Info size={16} /> SimPy — средняя доля отпущенной энергии по seed; разрыв показывает отличие MILP от симуляции. Статус относится только к заданной модели.</p>
              </section>
              <section className="detail-card defense-card" aria-labelledby="quality-title"><div className="detail-title"><h3 id="quality-title">Качество входа</h3><span className="small-caption">источник решения</span></div>
                <p className="quality-callout">{result?.metadata?.input_quality?.demand_scope === "served_sessions_only" ? "История выполненных зарядок; скрытый необслуженный спрос неизвестен." : result?.metadata?.input_quality?.demand_scope === "mobility_potential" ? "Потенциальная публичная потребность рассчитана из переданных маршрутов, а не измерена для всего города." : result?.metadata?.input_quality?.demand_scope === "scenario_assumptions" ? "Спрос задан предположениями, а не измерен." : "Данные смешанного происхождения; проверьте источник каждой записи."}</p>
                <p className="quality-count">Записи спроса, площадок и узлов: {provenance.observed} наблюдаемых · {provenance.derived} вычисленных · {provenance.assumed} предположенных</p>
                {Boolean(result?.metadata?.input_quality?.warnings?.length) && <ul className="quality-warnings">{result?.metadata?.input_quality?.warnings.map((warning) => <li key={warning}>{inputWarningLabel(warning)}</li>)}</ul>}
                {result?.metadata?.input_sha256 && <p className="detail-foot">Вход SHA-256: <code>{result.metadata.input_sha256}</code></p>}
              </section>
            </div>
            <div className="defense-grid">
              <section className="detail-card defense-card" aria-labelledby="audit-title"><div className="detail-title"><h3 id="audit-title">Энергетический аудит</h3><span className="audit-status">{plan.verification?.passed ? "Ограничения соблюдены" : "Проверка не подтверждена"}</span></div>
                <dl className="audit-metrics"><div><dt>Макс. ошибка баланса</dt><dd>{plan.verification?.max_hourly_energy_balance_error_kwh === undefined ? "—" : `${precise(plan.verification.max_hourly_energy_balance_error_kwh)} кВт·ч`}</dd></div><div><dt>Перегрузка узла</dt><dd>{plan.verification?.max_grid_node_overload_kw === undefined ? "—" : `${precise(plan.verification.max_grid_node_overload_kw)} кВт`}</dd></div><div><dt>Превышение бюджета</dt><dd>{plan.verification?.max_budget_overrun_rub === undefined ? "—" : `${precise(plan.verification.max_budget_overrun_rub)} ₽`}</dd></div></dl>
                {auditRows.length > 0 && <div className="data-table-scroll" role="region" tabIndex={0} aria-label="Энергетический аудит по площадкам"><table className="data-table"><thead><tr><th scope="col">Площадка</th><th scope="col">Отпущено</th><th scope="col">Из сети</th><th scope="col">Пик сети</th></tr></thead><tbody>{auditRows.map((row) => <tr key={row.site_id}><th scope="row">{activeSpec.sites.find((site) => site.id === row.site_id)?.name || row.site_id}</th><td>{number(row.served_kwh)} кВт·ч</td><td>{number(row.grid_kwh)} кВт·ч</td><td>{precise(row.peak_grid_kw)} кВт</td></tr>)}</tbody></table></div>}
                <p className="detail-foot"><Info size={16} /> Проверка мощности и баланса в модели; электрический AC-режим сети не рассчитывался.{plan.verification?.energy_audit_truncated ? " Детальный аудит сокращён." : ""}</p>
              </section>
              <section className="detail-card defense-card" aria-labelledby="daily-title"><div className="detail-title"><h3 id="daily-title">Работа сети по дням</h3><span className="small-caption">SimPy · среднее по {operationalRuns.length} seed</span></div>
                {dayRows.length ? <div className="data-table-scroll" role="region" tabIndex={0} aria-label="Посуточная работа сети"><table className="data-table"><thead><tr><th scope="col">День</th><th scope="col">Прибытия</th><th scope="col">Отпущено</th><th scope="col">Из сети</th><th scope="col">Очередь на границе</th></tr></thead><tbody>{dayRows.map((row) => <tr key={row.day}><th scope="row">{row.day}</th><td>{precise(row.arrivals)}</td><td>{precise(row.delivered)} кВт·ч</td><td>{precise(row.grid)} кВт·ч</td><td>{precise(row.queue)}</td></tr>)}</tbody></table></div> : <p className="quality-callout">Посуточная симуляция для этого результата недоступна.</p>}
                <p className="detail-foot"><Info size={16} /> Один повторяющийся суточный профиль спроса; это модельная проверка, не фактическая история года.</p>
              </section>
            </div>
          </section> : !runId && <section className="empty-result"><span className="empty-icon"><Zap size={24} /></span><div><h2>План ещё не рассчитан</h2><p>Задайте цель и бюджет. Система сравнит доступные площадки и ограничения сети.</p></div><ArrowRight size={21} /></section>}
          </div>
        </div>
      </div>
    </main>
  </div>;
}
