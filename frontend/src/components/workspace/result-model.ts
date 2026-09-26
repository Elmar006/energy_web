import type { PlanningSpec } from "@/lib/planning";

export type Selection = { site_id: string; option_id: string; year: number };
export type Optimization = {
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
  risk_metrics?: {
    cvar_alpha?: number;
    cvar_loss_rub?: number;
    cvar_unmet_kwh?: number;
  };
  investment_rub_by_year?: { year: number; rub: number }[];
  service_by_year?: {
    scenario_id: string;
    year: number;
    demand_kwh: number;
    served_kwh: number;
    unmet_kwh: number;
  }[];
  energy_audit?: {
    scenario_id: string;
    year: number;
    site_id: string;
    served_kwh: number;
    grid_kwh: number;
    peak_grid_kw: number;
    peak_station_kw: number;
    pv_used_kwh?: number;
    pv_available_kwh?: number;
    battery_charge_kwh?: number;
    battery_discharge_kwh?: number;
    battery_soc_start_kwh?: number;
    battery_soc_end_kwh?: number;
  }[];
  verification?: {
    passed?: boolean;
    max_hourly_energy_balance_error_kwh?: number;
    max_grid_node_overload_kw?: number;
    max_budget_overrun_rub?: number;
    energy_audit_truncated?: boolean;
  };
};
export type Simulation = {
  year: number;
  scenario_id: string;
  seed: number;
  arrivals: number;
  served_sessions: number;
  refused_sessions: number;
  mean_wait_minutes: number | null;
  p95_wait_minutes: number | null;
  requested_energy_kwh?: number;
  energy_kwh?: number;
  day_dispatch?: {
    day_index: number;
    arrivals: number;
    queued_sessions_at_boundary: number;
    dispatch_by_site: { site_id: string; load_kwh: number; grid_kwh: number }[];
  }[];
};
export type Explanation = {
  site_id: string;
  status: string;
  lost_served_kwh: Record<string, number> | null;
  replacement_sites: string[];
  method: string;
};
export type OperationalValidation = {
  scenario_id: string;
  year: number;
  seeds: number;
  optimized_service_fraction: number;
  simulated_service_fraction_mean: number;
  service_gap_percentage_points: number;
};
export type OperationalEconomics = {
  scenario_id: string;
  optimized_npv_rub: number;
  simulated_npv_rub_mean: number;
  simulated_npv_rub_min: number;
  simulated_npv_rub_max: number;
  optimism_gap_rub: number;
  profitability_sign_changed: boolean;
};
export type Acceptance = {
  status: string;
  reason: string;
  conditions?: {
    scenario_id: string;
    year: number;
    status?: string;
    metrics?: Record<
      string,
      {
        status?: string;
        threshold?: number;
        mean?: number;
        lower_95?: number;
        upper_95?: number;
        reason?: string;
      }
    >;
  }[];
};
export type Alternative = {
  target_service_fraction: number;
  achieved_min_service_fraction: number | null;
  same_investment_as_target: number | null;
  optimization: Optimization;
  operational_validation?: OperationalValidation[];
  operational_economics?: OperationalEconomics[];
  service_acceptance?: Acceptance;
};
export type InputQuality = {
  demand_scope: string;
  warnings: string[];
  observed_session_zone_ids: string[];
  parametric_zone_ids: string[];
  mobility_derived_zone_ids?: string[];
  mobility_sources?: { source: string; source_kind: string; sha256: string }[];
};
export type Result = {
  optimization: Optimization;
  simulation: Simulation[];
  explanations?: Explanation[];
  alternatives?: Alternative[];
  operational_validation?: OperationalValidation[];
  operational_economics?: OperationalEconomics[];
  service_acceptance?: Acceptance;
  improvement?: {
    method?: string;
    iterations?: {
      iteration?: number;
      status?: string;
      reason?: string;
      selected_for_holdout?: boolean;
      added_site_id?: string;
    }[];
  };
  metadata?: {
    input_quality?: InputQuality;
    input_sha256?: string;
    simulation_days?: number;
  };
};
export type Run = {
  id: string;
  scenario_id: string;
  state: string;
  error_detail?: string;
  run_spec?: {
    schema_version: string;
    mode: string;
    simulation_seeds: number[];
    development_seeds?: number[];
    simulation_days: number;
    model_version: string;
  };
  scenario_sha256?: string;
  run_spec_sha256?: string;
  execution_sha256?: string;
  run_spec_origin?: string;
};
export type SavedScenario = { id: string; name: string; spec: PlanningSpec };
export type ScenarioSummary = {
  id: string;
  name: string;
  sha256: string;
  created_at: string;
};

export const money = (value: number) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(
    value / 1_000_000,
  );
export const number = (value: number) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);
export const precise = (value: number) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);
export const solverStatus = (value: string) =>
  ({
    optimal: "Оптимально",
    feasible: "Допустимо",
    infeasible: "Невозможно",
    error: "Ошибка",
  })[value as "optimal" | "feasible" | "infeasible" | "error"] ?? value;
export const inputWarningLabel = (value: string) =>
  ({
    "Observed charging sessions describe fulfilled charging only; latent unmet demand is unknown.":
      "История зарядок охватывает только выполненные сессии; скрытый неудовлетворённый спрос неизвестен.",
    "The 'observed' source label is supplied by the importer and has not been independently verified.":
      "Метка «наблюдалось» заявлена при импорте и не проверена независимо.",
    "Session export day-by-day completeness is unverified for some zones; days without records are rejected unless full coverage is explicitly asserted.":
      "Для части зон полнота выгрузки по дням не подтверждена; пустые дни требуют явного заявления о полном покрытии.",
    "Complete day-by-day session coverage was asserted by the importer, not independently verified.":
      "Полнота истории по дням заявлена поставщиком, но не проверена независимо.",
    "Hourly charging load was apportioned uniformly across each session duration; interval meter readings were not supplied.":
      "Почасовая нагрузка распределена по длительности сессий; интервальных показаний счётчика нет.",
    "Some session profiles are declared assumed; their apparent precision does not imply measurement.":
      "Часть профилей сессий предположена; точные числа не означают, что они измерены.",
    "Zones without session profiles infer arrivals from hourly energy and assumed mean session size.":
      "В зонах без истории сессий прибытия оценены из почасовой энергии и предполагаемого размера сессии.",
    "At least one session profile has fewer than 7 days or 30 sessions; its temporal and energy distributions are weakly estimated.":
      "Для части профилей доступно менее 7 дней или 30 сессий; распределения оценены слабо.",
    "At least one grid headroom profile is not labeled observed; connection feasibility remains scenario-based.":
      "Резерв мощности хотя бы одного узла не подтверждён наблюдениями; подключение остаётся сценарным допущением.",
  })[value] ?? value;
export const plural = (
  value: number,
  one: string,
  few: string,
  many: string,
) => {
  const mod100 = value % 100,
    mod10 = value % 10;
  return (
    value +
    " " +
    (mod100 >= 11 && mod100 <= 14
      ? many
      : mod10 === 1
        ? one
        : mod10 >= 2 && mod10 <= 4
          ? few
          : many)
  );
};
