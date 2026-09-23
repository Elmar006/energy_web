export type ProvenanceKind = "observed" | "derived" | "assumed";

export type MapSite = {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  provenance?: { kind: ProvenanceKind; source: string };
};

export type MapZone = {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  provenance?: { kind: ProvenanceKind; source: string };
};

export type PlanningSpec = {
  id: string;
  sites: MapSite[];
  zones: MapZone[];
  grid_nodes: { id: string; provenance?: { kind: ProvenanceKind; source: string } }[];
  scenarios: { id: string }[];
  datasets?: {
    name: string;
    role: string;
    kind: ProvenanceKind;
    source: string;
    sha256: string;
    license?: string | null;
  }[];
  parameters: {
    years: number[];
    mode: "city" | "operator";
    total_budget_rub: number;
  };
};

export function isPlanningSpec(value: unknown): value is PlanningSpec {
  if (!value || typeof value !== "object") return false;
  const spec = value as Partial<PlanningSpec>;
  const hasPoint = (point: MapSite | MapZone) => typeof point?.id === "string" && typeof point?.name === "string" &&
    Number.isFinite(point.latitude) && Number.isFinite(point.longitude);
  return typeof spec.id === "string" && Array.isArray(spec.sites) && spec.sites.length > 0 && spec.sites.every(hasPoint) &&
    Array.isArray(spec.zones) && spec.zones.length > 0 && spec.zones.every(hasPoint) &&
    Array.isArray(spec.grid_nodes) && Array.isArray(spec.scenarios) && spec.scenarios.length > 0 &&
    Array.isArray(spec.parameters?.years) && spec.parameters.years.length > 0 &&
    Number.isFinite(spec.parameters?.total_budget_rub) &&
    (spec.parameters?.mode === "city" || spec.parameters?.mode === "operator");
}

export function provenanceSummary(spec: PlanningSpec) {
  const items = [...spec.sites, ...spec.zones, ...spec.grid_nodes];
  return {
    observed: items.filter((item) => item.provenance?.kind === "observed").length,
    derived: items.filter((item) => item.provenance?.kind === "derived").length,
    assumed: items.filter((item) => item.provenance?.kind === "assumed").length,
  };
}
