"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import SectionTabs from "@/components/ui/section-tabs";
import Territory from "./territory";
import {
  ArrowRight,
  BatteryCharging,
  Check,
  ChevronRight,
  Info,
  Download,
  Zap,
} from "lucide-react";
import type { PlanningSpec } from "@/lib/planning";
import ResultInsights from "@/components/result-insights";
import AlternativeDetails from "@/components/alternative-details";
import SimulationDistribution from "@/components/simulation-distribution";
import EnergyAuditDetails from "@/components/energy-audit-details";
import {
  inputWarningLabel,
  money,
  number,
  plural,
  precise,
  solverStatus,
  type Result,
  type Run,
} from "./result-model";

const PlanningMap = dynamic(() => import("@/components/planning-map"), {
  ssr: false,
  loading: () => <div className="map-loading">Загружаем карту…</div>,
});

const resultTabs = [
  { id: "overview", label: "Сводка" }, { id: "territory", label: "Территория" },
  { id: "operations", label: "Эксплуатация", compactLabel: "Работа" }, { id: "energy", label: "Энергетика", compactLabel: "Энергия" },
  { id: "economics", label: "Экономика" }, { id: "compare", label: "Сравнение" },
  { id: "evidence", label: "Данные и протокол", compactLabel: "Протокол" },
] as const;
type ResultTab = typeof resultTabs[number]["id"];

type Props = {
  activeSpec: PlanningSpec;
  result: Result | null;
  run: Run | null;
  runId: string | null;
  error: string;
  provenance: { observed: number; derived: number; assumed: number };
  onCancel: () => Promise<void>;
};

export default function PlanningView({
  activeSpec,
  result,
  run,
  runId,
  error,
  provenance,
  onCancel,
}: Props) {
  const [tab, setTab] = useState<ResultTab>("overview");
  const [selectedSite, setSelectedSite] = useState("");
  const [scenarioFilter, setScenarioFilter] = useState("");
  const [yearFilter, setYearFilter] = useState<number | null>(null);
  const plan = result?.optimization;
  const primaryScenario = activeSpec.scenarios.some(s => s.id === scenarioFilter) ? scenarioFilter : activeSpec.scenarios[0].id;
  const firstYear = yearFilter !== null && activeSpec.parameters.years.includes(yearFilter) ? yearFilter : activeSpec.parameters.years[0];
  const yearsLabel =
    activeSpec.parameters.years.length > 1
      ? `${activeSpec.parameters.years[0]}–${activeSpec.parameters.years.at(-1)}`
      : String(activeSpec.parameters.years[0]);
  const yearService = plan?.service_by_year?.find(row => row.scenario_id === primaryScenario && row.year === firstYear);
  const base = yearService?.served_kwh ?? plan?.served_kwh[primaryScenario];
  const unmet = yearService?.unmet_kwh ?? plan?.unmet_kwh[primaryScenario];
  const rate = base !== undefined && unmet !== undefined && base + unmet > 0 ? Math.round((base / (base + unmet)) * 100) : null;
  const simulations =
    result?.simulation.filter(
      (s) => s.scenario_id === primaryScenario && s.year === firstYear,
    ) || [];
  const measuredWaits = simulations
    .map((sample) => sample.p95_wait_minutes)
    .filter((value): value is number => value !== null && value !== undefined);
  const avgWait = measuredWaits.length
    ? measuredWaits.reduce((total, value) => total + value, 0) /
      measuredWaits.length
    : null;
  const scenarios = plan ? Object.keys(plan.served_kwh) : [];
  const comparison = plan
    ? [
        {
          name: "Основной план",
          optimization: plan,
          validation: result?.operational_validation,
          economics: result?.operational_economics,
          acceptance: result?.service_acceptance,
        },
        ...(result?.alternatives || []).map((alternative) => ({
          name: `Порог ${Math.round(alternative.target_service_fraction * 100)}%`,
          optimization: alternative.optimization,
          validation: alternative.operational_validation,
          economics: alternative.operational_economics,
          acceptance: alternative.service_acceptance,
        })),
      ]
    : [];
  const operationalRuns = simulations.filter((run) => run.day_dispatch?.length);
  const dayCount = Math.max(
    0,
    ...operationalRuns.map((run) => run.day_dispatch?.length || 0),
  );
  const dayRows = Array.from({ length: dayCount }, (_, day) => {
    const rows = operationalRuns
      .map((run) => run.day_dispatch?.[day])
      .filter((row) => row !== undefined);
    const divisor = rows.length || 1;
    return {
      day: day + 1,
      arrivals: rows.reduce((sum, row) => sum + row.arrivals, 0) / divisor,
      delivered:
        rows.reduce(
          (sum, row) =>
            sum +
            row.dispatch_by_site.reduce(
              (total, site) => total + site.load_kwh,
              0,
            ),
          0,
        ) / divisor,
      grid:
        rows.reduce(
          (sum, row) =>
            sum +
            row.dispatch_by_site.reduce(
              (total, site) => total + site.grid_kwh,
              0,
            ),
          0,
        ) / divisor,
      queue:
        rows.reduce((sum, row) => sum + row.queued_sessions_at_boundary, 0) /
        divisor,
    };
  });
  const auditRows =
    plan?.energy_audit?.filter(
      (row) => row.scenario_id === primaryScenario && row.year === firstYear,
    ) || [];

  return (
    <div className="planning-content">
      <SectionTabs items={resultTabs} value={tab} onChange={setTab} label="Представления расчёта">
      {plan && <div className="result-filters"><label>Сценарий<select value={primaryScenario} onChange={e => setScenarioFilter(e.target.value)}>{activeSpec.scenarios.map(s => <option key={s.id} value={s.id}>{s.id}</option>)}</select></label><label>Год<select value={firstYear} onChange={e => setYearFilter(Number(e.target.value))}>{activeSpec.parameters.years.map(year => <option key={year}>{year}</option>)}</select></label><span className="small-caption">NPV — за весь инвестиционный горизонт</span></div>}
      <section hidden={tab !== "territory" && (Boolean(plan) || tab !== "overview")} className="map-panel" aria-labelledby="map-title">
        <div className="section-head">
          <div>
            <h2 id="map-title">Площадки и зоны спроса</h2>
          </div>
          <span className="section-meta">
            {plural(
              activeSpec.sites.length,
              "площадка",
              "площадки",
              "площадок",
            )}{" "}
            · {plural(activeSpec.grid_nodes.length, "узел", "узла", "узлов")}{" "}
            сети
          </span>
        </div>
        <PlanningMap
          sites={activeSpec.sites}
          zones={activeSpec.zones}
          selected={plan?.selected}
          activeSiteId={selectedSite}
          onSelectSite={setSelectedSite}
        />
        <Territory spec={activeSpec} plan={plan} explanations={result?.explanations} scenario={primaryScenario} selectedSite={selectedSite} onSelect={setSelectedSite} />
      </section>

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      {runId &&
        !result &&
        run?.state !== "failed" &&
        run?.state !== "cancelled" && (
          <section className="calculating" role="status" aria-live="polite">
            <span className="loading-orbit" />
            <div>
              <strong>Расчёт плана</strong>
              <p>
                {run?.state === "running" ? "Выполняется" : "В очереди"}
              </p>
            </div>
            <button
              className="secondary-button"
              onClick={() => void onCancel()}
            >
              Отменить
            </button>
          </section>
        )}
      {run?.state === "cancelled" && (
        <section className="empty-result">
          <span className="empty-icon">
            <Info size={24} />
          </span>
          <div>
            <h2>Расчёт отменён</h2>
            <p>Можно изменить настройки и запустить новый расчёт.</p>
          </div>
        </section>
      )}

      {plan && plan.status !== "optimal" && plan.status !== "feasible" ? (
        <section className="empty-result" role="alert">
          <span className="empty-icon">
            <Info size={24} />
          </span>
          <div>
            <h2>
              {plan.status === "infeasible"
                ? "Ограничения несовместимы"
                : "Не удалось получить план"}
            </h2>
            <p>
              {plan.diagnostic ||
                "Проверьте исходные данные и ограничения сценария."}
            </p>
          </div>
        </section>
      ) : plan ? (
        <section
          className="results"
          aria-labelledby="results-title"
          aria-live="polite"
        >
          <div className="results-heading">
            <div>
              <h2 id="results-title">Результат</h2>
            </div>
            <span className="result-badge">
              <Check size={15} /> Расчёт завершён
            </span>
            <button type="button" className="secondary-button compact-button" onClick={() => {
              const file = new Blob([JSON.stringify({ schema_version: "workspace-export-v1", run, result, scenario: activeSpec }, null, 2)], { type: "application/json" });
              const url = URL.createObjectURL(file);
              const link = document.createElement("a"); link.href = url; link.download = `energy-run-${runId || "result"}.json`;
              link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            }}><Download size={14} aria-hidden="true" />Экспорт JSON</button>
          </div>
          <div className="metric-grid" hidden={tab !== "overview"}>
            <div className="metric-card">
              <span>Обслуживание · оптимизатор</span>
              <strong>{rate === null ? "—" : `${rate}%`}</strong>
              <small>{primaryScenario} · {yearService ? firstYear : "весь горизонт"}</small>
            </div>
            <div className="metric-card">
              <span>Выбранные площадки</span>
              <strong>{plan.selected.length}</strong>
              <small>Строительство в {yearsLabel}</small>
            </div>
            <div className="metric-card">
              <span>NPV · {primaryScenario}</span>
              <strong>
                {plan.cashflow_rub[primaryScenario] === undefined ? "—" : money(plan.cashflow_rub[primaryScenario])} <em>млн ₽</em>
              </strong>
              <small>Оптимизатор · весь горизонт</small>
            </div>
            <div className="metric-card">
              <span>Ожидание · симуляция</span>
              <strong>
                {avgWait === null ? "—" : `${Math.round(avgWait)} мин`}
              </strong>
              <small>
                Среднее p95 · {firstYear} · {simulations.length} прогонов
              </small>
            </div>
          </div>
          <ResultInsights result={result!} run={run} view={tab} />
          <div hidden={tab !== "operations"}><SimulationDistribution runs={simulations} /></div>
          <div hidden={tab !== "energy"}><EnergyAuditDetails
            scenarioId={primaryScenario}
            yearValue={firstYear}
            rows={plan.energy_audit || []}
            siteNames={Object.fromEntries(
              activeSpec.sites.map((site) => [site.id, site.name]),
            )}
            truncated={plan.verification?.energy_audit_truncated}
          /></div>
          <div className="result-lower" hidden={tab !== "overview" && tab !== "territory"}>
            <div className="detail-card">
              <div className="detail-title">
                <h3>Этапы строительства</h3>
                <ChevronRight size={18} />
              </div>
              <ul className="station-list">
                {plan.selected.map((entry) => {
                  const site = activeSpec.sites.find(
                    (s) => s.id === entry.site_id,
                  );
                  return (
                    <li key={entry.site_id}>
                      <span className="station-indicator" />
                      <div>
                        <strong>{site?.name || entry.site_id}</strong>
                        <small>
                          {entry.option_id.toUpperCase()} · ввод {entry.year}
                        </small>
                      </div>
                      <span className="year-pill">{entry.year}</span>
                    </li>
                  );
                })}
              </ul>
              {plan.selected.length === 0 && (
                <p className="detail-foot">
                  <Info size={16} />{" "}
                  {activeSpec.parameters.mode === "operator"
                    ? "При заданных условиях строительство не улучшает экономический результат."
                    : "При заданных ограничениях новые площадки не выбраны."}
                </p>
              )}
              {plan.grid_upgrades.length > 0 && (
                <p className="detail-foot">
                  <Zap size={16} /> Усиление сети:{" "}
                  {plan.grid_upgrades.map((x) => x.grid_node_id).join(", ")}
                </p>
              )}
              {plan.solar.length > 0 && (
                <p className="detail-foot">
                  <BatteryCharging size={16} /> Локальная генерация:{" "}
                  {plan.solar.map((x) => `${x.site_id} ${x.kw} кВт`).join(", ")}
                </p>
              )}
            </div>
            <div className="detail-card">
              <div className="detail-title">
                <h3>Устойчивость к росту спроса</h3>
                <span className="small-caption">кВт·ч за период</span>
              </div>
              <div className="scenario-bars">
                {scenarios.map((key) => {
                    const used = plan.served_kwh[key],
                      missed = plan.unmet_kwh[key];
                    if (used === undefined || missed === undefined) return <div key={key} className="scenario-row"><strong>{key}</strong><span>Нет данных об обслуженной энергии</span></div>;
                  const percent =
                    used + missed ? (used / (used + missed)) * 100 : 0;
                  return (
                    <div key={key} className="scenario-row">
                      <div>
                        <strong>{key}</strong>
                        <span>{Math.round(percent)}% покрыто</span>
                      </div>
                      <div
                        className="bar-track"
                        role="img"
                        aria-label={`${key}: обслужено ${number(used)} киловатт-часов из ${number(used + missed)}`}
                      >
                        <span style={{ width: `${percent}%` }} />
                      </div>
                      <small>
                        {number(used)} / {number(used + missed)} кВт·ч
                      </small>
                    </div>
                  );
                })}
              </div>
              {plan.risk_metrics?.cvar_alpha !== undefined &&
                (plan.risk_metrics.cvar_loss_rub !== undefined ||
                  plan.risk_metrics.cvar_unmet_kwh !== undefined) && (
                  <div className="risk-metric">
                    <span>
                      CVaR · худшие{" "}
                      {precise((1 - plan.risk_metrics.cvar_alpha) * 100)}%
                      вероятности
                    </span>
                    <strong>
                      {plan.risk_metrics.cvar_loss_rub !== undefined
                        ? `${precise(plan.risk_metrics.cvar_loss_rub)} ₽`
                        : `${precise(plan.risk_metrics.cvar_unmet_kwh ?? 0)} кВт·ч`}
                    </strong>
                    <small>
                      Допустимый предел:{" "}
                      {plan.risk_metrics.cvar_loss_rub !== undefined
                        ? activeSpec.parameters.max_cvar_loss_rub == null ? "не задан" : `${precise(activeSpec.parameters.max_cvar_loss_rub)} ₽ убытка NPV`
                        : activeSpec.parameters.max_cvar_unmet_kwh == null ? "не задан" : `${precise(activeSpec.parameters.max_cvar_unmet_kwh)} кВт·ч необслуженного спроса`}
                      . Среднее по худшему хвосту заданных сценариев.
                    </small>
                  </div>
                )}
              <p className="detail-foot">
                <Info size={16} /> При изменении предположений план нужно
                пересчитать.
              </p>
            </div>
          </div>
          {tab === "territory" && Boolean(result?.explanations?.length) && (
            <div className="detail-card explanation-card">
              <div className="detail-title">
                <h3>Почему выбраны площадки</h3>
                <span className="small-caption">пересчёт без объекта</span>
              </div>
              <div className="explanation-list">
                {result?.explanations?.map((item) => {
                  const site = activeSpec.sites.find(
                    (entry) => entry.id === item.site_id,
                  );
                  const lost = item.lost_served_kwh?.[primaryScenario];
                  return (
                    <div className="explanation-row" key={item.site_id}>
                      <strong>{site?.name || item.site_id}</strong>
                      <span>
                        {item.status === "fixed"
                          ? "Объект закреплён"
                          : lost === undefined
                            ? "Альтернатива не найдена"
                            : lost >= 0.5
                              ? `Без объекта: −${number(lost)} кВт·ч обслуживания`
                              : "Спрос может покрыть другая площадка"}
                      </span>
                    </div>
                  );
                })}
              </div>
              <p className="detail-foot">
                <Info size={16} /> Эффект рассчитан повторной оптимизацией с
                исключением площадки.
              </p>
            </div>
          )}
          <div className="defense-grid" hidden={tab !== "compare" && tab !== "evidence"}>
            <section
              className="detail-card defense-card"
              aria-labelledby="alternatives-title"
              hidden={tab !== "compare"}
            >
              <div className="detail-title">
                <h3 id="alternatives-title">Основной план и альтернативы</h3>
                <span className="small-caption">
                  один вход · {primaryScenario} · {firstYear}
                </span>
              </div>
              <div
                className="data-table-scroll"
                role="region"
                tabIndex={0}
                aria-label="Сравнение планов"
              >
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">План</th>
                      <th scope="col">CAPEX всего</th>
                      <th scope="col">Энергия · симуляция</th>
                      <th scope="col">Отличие от модели</th>
                      <th scope="col">Статус решателя</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.map((row) => {
                      const validation = row.validation?.find(
                        (item) =>
                          item.scenario_id === primaryScenario &&
                          item.year === firstYear,
                      );
                      const capex =
                        row.optimization.investment_rub_by_year?.reduce(
                          (sum, item) => sum + item.rub,
                          0,
                        ) ?? null;
                      return (
                        <tr key={row.name}>
                          <th scope="row">{row.name}</th>
                          <td>
                            {capex === null ? "—" : `${money(capex)} млн ₽`}
                          </td>
                          <td>
                            {validation
                              ? `${precise(validation.simulated_service_fraction_mean * 100)}%`
                              : "—"}
                          </td>
                          <td>
                            {validation
                              ? `${precise(validation.service_gap_percentage_points)} п.п.`
                              : "—"}
                          </td>
                          <td>{solverStatus(row.optimization.status)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <AlternativeDetails alternatives={result?.alternatives || []} />
              <p className="detail-foot">
                <Info size={16} /> SimPy — средняя доля отпущенной энергии по
                seed; разрыв показывает отличие MILP от симуляции. Статус
                относится только к заданной модели.
              </p>
            </section>
            <section
              className="detail-card defense-card"
              aria-labelledby="quality-title"
              hidden={tab !== "evidence"}
            >
              <div className="detail-title">
                <h3 id="quality-title">Качество входа</h3>
              </div>
              <p className="quality-callout">
                {result?.metadata?.input_quality?.demand_scope ===
                "served_sessions_only"
                  ? "История сессий не учитывает неудовлетворённый спрос."
                  : result?.metadata?.input_quality?.demand_scope ===
                      "mobility_potential"
                    ? "Потенциальная публичная потребность рассчитана из переданных маршрутов, а не измерена для всего города."
                    : result?.metadata?.input_quality?.demand_scope ===
                        "scenario_assumptions"
                      ? "Спрос задан предположениями, а не измерен."
                      : "Данные смешанного происхождения; проверьте источник каждой записи."}
              </p>
              <p className="quality-count">
                Записи спроса, площадок и узлов: {provenance.observed}{" "}
                наблюдаемых · {provenance.derived} вычисленных ·{" "}
                {provenance.assumed} предположенных
              </p>
              {Boolean(result?.metadata?.input_quality?.warnings?.length) && (
                <ul className="quality-warnings">
                  {result?.metadata?.input_quality?.warnings.map((warning) => (
                    <li key={warning}>{inputWarningLabel(warning)}</li>
                  ))}
                </ul>
              )}
              {result?.metadata?.input_sha256 && (
                <p className="detail-foot">
                  Вход SHA-256: <code>{result.metadata.input_sha256}</code>
                </p>
              )}
            </section>
          </div>
          <div className="defense-grid" hidden={tab !== "energy" && tab !== "operations"}>
            <section
              className="detail-card defense-card"
              aria-labelledby="audit-title"
              hidden={tab !== "energy"}
            >
              <div className="detail-title">
                <h3 id="audit-title">Энергетический аудит</h3>
                <span className="audit-status">
                  {plan.verification?.passed
                    ? "Ограничения соблюдены"
                    : "Проверка не подтверждена"}
                </span>
              </div>
              <dl className="audit-metrics">
                <div>
                  <dt>Макс. ошибка баланса</dt>
                  <dd>
                    {plan.verification?.max_hourly_energy_balance_error_kwh ===
                    undefined
                      ? "—"
                      : `${precise(plan.verification.max_hourly_energy_balance_error_kwh)} кВт·ч`}
                  </dd>
                </div>
                <div>
                  <dt>Перегрузка узла</dt>
                  <dd>
                    {plan.verification?.max_grid_node_overload_kw === undefined
                      ? "—"
                      : `${precise(plan.verification.max_grid_node_overload_kw)} кВт`}
                  </dd>
                </div>
                <div>
                  <dt>Превышение бюджета</dt>
                  <dd>
                    {plan.verification?.max_budget_overrun_rub === undefined
                      ? "—"
                      : `${precise(plan.verification.max_budget_overrun_rub)} ₽`}
                  </dd>
                </div>
              </dl>
              {auditRows.length > 0 && (
                <div
                  className="data-table-scroll"
                  role="region"
                  tabIndex={0}
                  aria-label="Энергетический аудит по площадкам"
                >
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th scope="col">Площадка</th>
                        <th scope="col">Отпущено</th>
                        <th scope="col">Из сети</th>
                        <th scope="col">Пик сети</th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditRows.map((row) => (
                        <tr key={row.site_id}>
                          <th scope="row">
                            {activeSpec.sites.find(
                              (site) => site.id === row.site_id,
                            )?.name || row.site_id}
                          </th>
                          <td>{number(row.served_kwh)} кВт·ч</td>
                          <td>{number(row.grid_kwh)} кВт·ч</td>
                          <td>{precise(row.peak_grid_kw)} кВт</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="detail-foot">
                <Info size={16} /> Проверка мощности и баланса в модели;
                электрический AC-режим сети не рассчитывался.
                {plan.verification?.energy_audit_truncated
                  ? " Детальный аудит сокращён."
                  : ""}
              </p>
            </section>
            <section
              className="detail-card defense-card"
              aria-labelledby="daily-title"
              hidden={tab !== "operations"}
            >
              <div className="detail-title">
                <h3 id="daily-title">Работа сети по дням</h3>
                <span className="small-caption">
                  SimPy · среднее по {operationalRuns.length} seed
                </span>
              </div>
              {dayRows.length ? (
                <div
                  className="data-table-scroll"
                  role="region"
                  tabIndex={0}
                  aria-label="Посуточная работа сети"
                >
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th scope="col">День</th>
                        <th scope="col">Прибытия</th>
                        <th scope="col">Отпущено</th>
                        <th scope="col">Из сети</th>
                        <th scope="col">Очередь на границе</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dayRows.map((row) => (
                        <tr key={row.day}>
                          <th scope="row">{row.day}</th>
                          <td>{precise(row.arrivals)}</td>
                          <td>{precise(row.delivered)} кВт·ч</td>
                          <td>{precise(row.grid)} кВт·ч</td>
                          <td>{precise(row.queue)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="quality-callout">
                  Посуточная симуляция для этого результата недоступна.
                </p>
              )}
              <p className="detail-foot">
                <Info size={16} /> Модельная эксплуатация за расчётный период; календарь и происхождение спроса определяются входным сценарием. Это не фактическая история года.
              </p>
            </section>
          </div>
        </section>
      ) : (
        !runId && (tab === "overview" || tab === "territory") && (
          <section className="empty-result">
            <span className="empty-icon">
              <Zap size={24} />
            </span>
            <div>
              <h2>План ещё не рассчитан</h2>
              <p>
                Задайте цель и бюджет. Система сравнит доступные площадки и
                ограничения сети.
              </p>
            </div>
            <ArrowRight size={21} />
          </section>
        )
      )}
      {!plan && tab !== "overview" && tab !== "territory" && <div className="prerequisite"><h2>Сначала рассчитайте план</h2><p>Этот раздел появится после выполнения расчёта. Исходные площадки уже доступны во вкладке «Территория».</p><button className="secondary-button" onClick={() => setTab("overview")}>К настройке расчёта</button></div>}
      </SectionTabs>
    </div>
  );
}
