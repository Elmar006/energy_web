export type Mode = "operator" | "city";

const assumed = { source: "Синтетический конкурсный сценарий; инженерная проверка требуется", kind: "assumed" } as const;

const privateProfile = [3, 2, 2, 2, 2, 4, 8, 15, 25, 24, 20, 23, 30, 32, 27, 28, 34, 45, 55, 58, 48, 32, 20, 9];
const taxiProfile = [16, 14, 10, 9, 12, 17, 22, 28, 32, 30, 25, 30, 35, 32, 28, 30, 35, 42, 48, 50, 42, 31, 25, 20];
const fleetProfile = [0, 0, 0, 0, 0, 1, 3, 4, 2, 1, 1, 1, 2, 3, 4, 6, 10, 14, 20, 22, 18, 12, 6, 2];

export const demoSites = [
  { id: "west", name: "Площадка A · Запад", latitude: 56.8399, longitude: 60.5457, grid_node_id: "n-west", option_ids: ["ac", "dc60", "dc150"], battery_max_kwh: 80, battery_capex_per_kwh_rub: 11000, pv_max_kw: 25, pv_capex_per_kw_rub: 64000, provenance: assumed },
  { id: "centre", name: "Площадка B · Центр", latitude: 56.8370, longitude: 60.6031, grid_node_id: "n-centre", option_ids: ["ac", "dc60"], battery_max_kwh: 40, battery_capex_per_kwh_rub: 11000, pv_max_kw: 0, pv_capex_per_kw_rub: 0, provenance: assumed },
  { id: "east", name: "Площадка C · Восток", latitude: 56.8424, longitude: 60.6680, grid_node_id: "n-east", option_ids: ["ac", "dc60", "dc150"], battery_max_kwh: 80, battery_capex_per_kwh_rub: 11000, pv_max_kw: 25, pv_capex_per_kw_rub: 64000, provenance: assumed },
  { id: "south", name: "Площадка D · Юг", latitude: 56.7950, longitude: 60.6100, grid_node_id: "n-centre", option_ids: ["ac", "dc60"], battery_max_kwh: 0, battery_capex_per_kwh_rub: 0, pv_max_kw: 0, pv_capex_per_kw_rub: 0, provenance: assumed },
];

export const demoZones = [
  { id: "homes", name: "Жилые кварталы", latitude: 56.8435, longitude: 60.5630, group: "private", hourly_kwh: privateProfile, mean_session_kwh: 35, max_travel_minutes: 24, provenance: assumed },
  { id: "taxi", name: "Такси и деловой центр", latitude: 56.8340, longitude: 60.6160, group: "taxi", hourly_kwh: taxiProfile, mean_session_kwh: 40, max_travel_minutes: 18, provenance: assumed },
  { id: "fleet", name: "Корпоративный парк", latitude: 56.8060, longitude: 60.6350, group: "fleet", hourly_kwh: fleetProfile, mean_session_kwh: 45, max_travel_minutes: 20, provenance: assumed },
];

export function makeDemo(mode: Mode, budgetRub: number, demandPercent: number) {
  const multiplier = demandPercent / 100;
  return {
    id: `demo-${mode}-${budgetRub}-${demandPercent}`,
    zones: demoZones,
    sites: demoSites,
    options: [
      { id: "ac", ports: 2, charger_kw: 22, connection_kw: 44, capex_rub: 1100000, annual_fixed_rub: 90000, allowed_groups: ["private", "fleet"] },
      { id: "dc60", ports: 2, charger_kw: 60, connection_kw: 120, capex_rub: 2600000, annual_fixed_rub: 180000, allowed_groups: ["private", "taxi", "fleet"] },
      { id: "dc150", ports: 2, charger_kw: 150, connection_kw: 280, capex_rub: 5100000, annual_fixed_rub: 300000, allowed_groups: ["private", "taxi", "fleet"] },
    ],
    grid_nodes: [
      { id: "n-west", headroom_kw: Array(24).fill(105), upgrade_kw: 140, upgrade_capex_rub: 1500000, provenance: assumed },
      { id: "n-centre", headroom_kw: Array(24).fill(85), upgrade_kw: 110, upgrade_capex_rub: 1300000, provenance: assumed },
      { id: "n-east", headroom_kw: Array(24).fill(170), upgrade_kw: 100, upgrade_capex_rub: 1200000, provenance: assumed },
    ],
    scenarios: [
      { id: "базовый", demand_multiplier: [multiplier, multiplier * 1.2], tariff_multiplier: 1 },
      { id: "ускоренный рост", demand_multiplier: [multiplier * 1.25, multiplier * 1.55], tariff_multiplier: 1.07 },
    ],
    travel_edges: [
      { zone_id: "homes", site_id: "west", minutes: 7 }, { zone_id: "homes", site_id: "centre", minutes: 15 }, { zone_id: "homes", site_id: "east", minutes: 27 }, { zone_id: "homes", site_id: "south", minutes: 22 },
      { zone_id: "taxi", site_id: "west", minutes: 19 }, { zone_id: "taxi", site_id: "centre", minutes: 5 }, { zone_id: "taxi", site_id: "east", minutes: 12 }, { zone_id: "taxi", site_id: "south", minutes: 18 },
      { zone_id: "fleet", site_id: "west", minutes: 27 }, { zone_id: "fleet", site_id: "centre", minutes: 16 }, { zone_id: "fleet", site_id: "east", minutes: 14 }, { zone_id: "fleet", site_id: "south", minutes: 5 },
    ],
    parameters: {
      mode, risk: "worst_case" as const, years: [2027, 2028], annual_budgets_rub: [budgetRub * 0.7, budgetRub * 0.3], total_budget_rub: budgetRub,
      sale_rub_per_kwh: 32, purchase_rub_per_kwh: 9, discount_rate: 0.12,
      pv_hourly_factor: [0, 0, 0, 0, 0, 0.05, 0.12, 0.23, 0.39, 0.55, 0.7, 0.78, 0.8, 0.75, 0.62, 0.47, 0.28, 0.12, 0.02, 0, 0, 0, 0, 0],
      storage_efficiency: 0.9, storage_max_hours: 2, storage_degradation_rub_per_kwh: 2,
      minimum_zone_service: mode === "city" ? 0.25 : 0,
      solver_seconds: 90,
    },
  };
}
