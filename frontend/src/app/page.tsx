"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { Activity, ArrowRight, BatteryCharging, Check, ChevronRight, Clock3, Info, LogOut, MapPinned, ShieldCheck, Zap } from "lucide-react";
import type { Mode } from "@/lib/demo";
import { demoSites } from "@/lib/demo";

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
};
type Simulation = {
  year: number; scenario_id: string; seed: number;
  arrivals: number; served_sessions: number; refused_sessions: number;
  mean_wait_minutes: number | null; p95_wait_minutes: number | null;
};
type Explanation = { site_id: string; status: string; lost_served_kwh: Record<string, number> | null; replacement_sites: string[]; method: string };
type Result = { optimization: Optimization; simulation: Simulation[]; explanations?: Explanation[] };
type Run = { id: string; state: string; error_detail?: string };

const money = (value: number) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value / 1_000_000);
const number = (value: number) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);

export default function Home() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<Mode>("city");
  const [budget, setBudget] = useState(10);
  const [demand, setDemand] = useState(100);
  const [runId, setRunId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    const previous = new URLSearchParams(window.location.search).get("run");
    return previous && /^[0-9a-f-]{36}$/.test(previous) ? previous : null;
  });
  const [run, setRun] = useState<Run | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetch("/api/session").then((r) => r.json()).then((v) => setSignedIn(Boolean(v.signed_in))).catch(() => setSignedIn(false));
  }, []);

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
    if (!runId || !signedIn || result || run?.state === "failed") return;
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [runId, signedIn, result, run?.state, refresh]);

  async function login(event: React.FormEvent) {
    event.preventDefault(); setError("");
    const response = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) });
    if (!response.ok) { setError("Неверный пароль доступа"); return; }
    setSignedIn(true); setPassword("");
  }

  async function logout() {
    await fetch("/api/session", { method: "DELETE" });
    setSignedIn(false); setResult(null); setRun(null); setRunId(null);
    window.history.replaceState({}, "", "/");
  }

  async function start() {
    setSubmitting(true); setError(""); setResult(null); setRun(null);
    try {
      const response = await fetch("/api/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, budget: budget * 1_000_000, demand }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Не удалось запустить расчёт");
      setRunId(payload.run_id);
      window.history.replaceState({}, "", `?run=${payload.run_id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Ошибка запуска");
    } finally { setSubmitting(false); }
  }

  if (signedIn === null) return <main className="screen-centered"><p>Загружаем рабочее пространство…</p></main>;
  if (!signedIn) return (
    <main className="screen-centered"><div className="login-panel">
      <div className="brand-mark"><Zap size={23} strokeWidth={2.4} /></div>
      <p className="eyebrow">Платформа планирования</p>
      <h1>Вектор</h1>
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
  const base = plan?.served_kwh["базовый"] || 0;
  const unmet = plan?.unmet_kwh["базовый"] || 0;
  const rate = base + unmet > 0 ? Math.round(base / (base + unmet) * 100) : 0;
  const simulations = result?.simulation.filter((s) => s.scenario_id === "базовый" && s.year === 2027) || [];
  const avgWait = simulations.length ? simulations.reduce((total, s) => total + (s.p95_wait_minutes || 0), 0) / simulations.length : null;
  const scenarios = plan ? Object.keys(plan.served_kwh) : [];

  return <div className="app-shell">
    <header className="app-header">
      <div className="brand"><span className="brand-mark small"><Zap size={19} strokeWidth={2.4} /></span><strong>Вектор</strong><span className="brand-divider" /><span className="brand-caption">Планирование инфраструктуры</span></div>
      <div className="header-status"><span className="status-pulse" aria-hidden="true" /><span className="header-status-label">Демо-доступ</span><button type="button" className="logout-button" onClick={logout} aria-label="Выйти из рабочего пространства" title="Выйти"><LogOut size={16} /></button></div>
    </header>

    <main className="workspace">
      <section className="page-intro" aria-labelledby="page-title">
        <div><p className="eyebrow"><MapPinned size={14} /> ПРОЕКТ / СЦЕНАРНОЕ ПЛАНИРОВАНИЕ</p><h1 id="page-title">Развитие зарядной сети</h1><p>Выберите условия и получите план размещения с проверкой энергосети и спроса.</p></div>
        <div className="intro-note"><ShieldCheck size={19} /><span>Пилотный сценарий<br /><strong>Екатеринбург · синтетические данные</strong></span></div>
      </section>

      <div className="workspace-grid">
        <aside className="control-panel" aria-labelledby="scenario-title">
          <div className="panel-heading"><span className="panel-icon"><Activity size={18} /></span><div><p className="eyebrow">ПАРАМЕТРЫ РАСЧЁТА</p><h2 id="scenario-title">Новый сценарий</h2></div></div>
          <fieldset className="mode-options"><legend>Цель планирования</legend>
            <label className={`mode-card ${mode === "city" ? "active" : ""}`}><input type="radio" name="mode" checked={mode === "city"} onChange={() => setMode("city")} /><span className="mode-text"><strong>Для города</strong><small>Максимальная доступность зарядки</small></span><span className="mode-check">{mode === "city" && <Check size={15} />}</span></label>
            <label className={`mode-card ${mode === "operator" ? "active" : ""}`}><input type="radio" name="mode" checked={mode === "operator"} onChange={() => setMode("operator")} /><span className="mode-text"><strong>Для оператора</strong><small>Экономика развития сети</small></span><span className="mode-check">{mode === "operator" && <Check size={15} />}</span></label>
          </fieldset>
          <div className="field-block"><label htmlFor="budget">Инвестиционный бюджет <strong>{budget} млн ₽</strong></label><input id="budget" type="range" min="1" max="50" step="1" value={budget} onChange={(e) => setBudget(Number(e.target.value))} /><div className="range-ends"><span>1 млн ₽</span><span>50 млн ₽</span></div></div>
          <div className="field-block"><label htmlFor="demand">Уровень спроса <strong>{demand}%</strong></label><input id="demand" type="range" min="50" max="200" step="10" value={demand} onChange={(e) => setDemand(Number(e.target.value))} /><div className="range-ends"><span>50%</span><span>200%</span></div></div>
          <div className="parameters-summary"><div><Clock3 size={17} /><span>Горизонт</span><strong>2027–2028</strong></div><div><Zap size={17} /><span>Энергосеть</span><strong>3 узла</strong></div><div><MapPinned size={17} /><span>Площадки</span><strong>4 кандидата</strong></div></div>
          <button className="primary-button run-button" onClick={start} disabled={submitting || (runId !== null && run?.state !== "succeeded" && run?.state !== "failed" && run?.state !== "cancelled")}>
            {submitting ? "Запускаем…" : runId && !result && run?.state !== "failed" ? "Идёт расчёт…" : "Рассчитать план"}<ArrowRight size={18} />
          </button>
          <p className="panel-disclaimer"><Info size={15} /> Все мощности, цены и спрос в пилоте — сценарные предположения. Результат не является согласованием подключения.</p>
        </aside>

        <div className="main-column">
          <section className="map-panel" aria-labelledby="map-title"><div className="section-head"><div><p className="eyebrow">ПРОСТРАНСТВЕННАЯ МОДЕЛЬ</p><h2 id="map-title">Площадки и зоны спроса</h2></div><span className="section-meta">{demoSites.length} площадки · 3 узла сети</span></div><PlanningMap selected={plan?.selected} /></section>

          {error && <div className="error-banner" role="alert">{error}</div>}
          {runId && !result && run?.state !== "failed" && <section className="calculating" role="status" aria-live="polite"><span className="loading-orbit" /><div><strong>Рассчитываем инфраструктуру</strong><p>Проверяем бюджет, энергосеть и работу станций. Состояние: {run?.state === "running" ? "выполняется" : "в очереди"}.</p></div></section>}

          {plan ? <section className="results" aria-labelledby="results-title" aria-live="polite">
            <div className="results-heading"><div><p className="eyebrow">РЕЗУЛЬТАТ / {plan.status === "optimal" ? "ОПТИМАЛЬНОЕ РЕШЕНИЕ" : "ДОПУСТИМОЕ РЕШЕНИЕ"}</p><h2 id="results-title">План развития сети</h2></div><span className="result-badge"><Check size={15} /> Расчёт завершён</span></div>
            <div className="metric-grid">
              <div className="metric-card"><span>Обслуженный спрос</span><strong>{rate}%</strong><small>Базовый сценарий · суммарно</small></div>
              <div className="metric-card"><span>Выбранные площадки</span><strong>{plan.selected.length}</strong><small>Строительство в 2027–2028</small></div>
              <div className="metric-card"><span>NPV · базовый сценарий</span><strong>{money(plan.cashflow_rub["базовый"] || 0)} <em>млн ₽</em></strong><small>По заданным тарифам и затратам</small></div>
              <div className="metric-card"><span>p95 ожидания</span><strong>{avgWait === null ? "—" : `${Math.round(avgWait)} мин`}</strong><small>Симуляция · 2027</small></div>
            </div>
            <div className="result-lower">
              <div className="detail-card"><div className="detail-title"><h3>Этапы строительства</h3><ChevronRight size={18} /></div>
                <ul className="station-list">{plan.selected.map((entry) => {
                  const site = demoSites.find((s) => s.id === entry.site_id);
                  return <li key={entry.site_id}><span className="station-indicator" /><div><strong>{site?.name || entry.site_id}</strong><small>{entry.option_id.toUpperCase()} · ввод {entry.year}</small></div><span className="year-pill">{entry.year}</span></li>;
                })}</ul>
                {plan.grid_upgrades.length > 0 && <p className="detail-foot"><Zap size={16} /> Усиление сети: {plan.grid_upgrades.map((x) => x.grid_node_id).join(", ")}</p>}
                {plan.solar.length > 0 && <p className="detail-foot"><BatteryCharging size={16} /> Локальная генерация: {plan.solar.map((x) => `${x.site_id} ${x.kw} кВт`).join(", ")}</p>}
              </div>
              <div className="detail-card"><div className="detail-title"><h3>Устойчивость к росту спроса</h3><span className="small-caption">кВт·ч за период</span></div>
                <div className="scenario-bars">{scenarios.map((key) => {
                  const used = plan.served_kwh[key] || 0, missed = plan.unmet_kwh[key] || 0;
                  const percent = used + missed ? used / (used + missed) * 100 : 0;
                  return <div key={key} className="scenario-row"><div><strong>{key}</strong><span>{Math.round(percent)}% покрыто</span></div><div className="bar-track" role="img" aria-label={`${key}: обслужено ${number(used)} киловатт-часов из ${number(used + missed)}`}><span style={{ width: `${percent}%` }} /></div><small>{number(used)} / {number(used + missed)} кВт·ч</small></div>;
                })}</div>
                <p className="detail-foot"><Info size={16} /> При изменении предположений план нужно пересчитать.</p>
              </div>
            </div>
            {Boolean(result?.explanations?.length) && <div className="detail-card explanation-card"><div className="detail-title"><h3>Почему выбраны площадки</h3><span className="small-caption">пересчёт без объекта</span></div>
              <div className="explanation-list">{result?.explanations?.map((item) => {
                const site = demoSites.find((entry) => entry.id === item.site_id);
                const lost = item.lost_served_kwh?.["базовый"];
                return <div className="explanation-row" key={item.site_id}><strong>{site?.name || item.site_id}</strong><span>{item.status === "fixed" ? "Объект закреплён" : lost === undefined ? "Альтернатива не найдена" : lost > 0 ? `Без объекта: −${number(lost)} кВт·ч обслуживания` : "Спрос может покрыть другая площадка"}</span></div>;
              })}</div>
              <p className="detail-foot"><Info size={16} /> Эффект рассчитан повторной оптимизацией с исключением площадки.</p>
            </div>}
          </section> : !runId && <section className="empty-result"><span className="empty-icon"><Zap size={24} /></span><div><h2>План ещё не рассчитан</h2><p>Задайте цель и бюджет. Система сравнит доступные площадки и ограничения сети.</p></div><ArrowRight size={21} /></section>}
        </div>
      </div>
    </main>
  </div>;
}
