"use client";

import type { PlanningSpec } from "@/lib/planning";
import { Download } from "lucide-react";

export type Scenario = {
  id: string;
  name: string;
  spec: PlanningSpec;
  sha256?: string;
};
export type Dataset = {
  id: string;
  name: string;
  source: string;
  kind: string;
  checksum: string;
  format: string;
  role?: string;
};
export type Props = {
  view: "data" | "mobility" | "models";
  section: "editor" | "csv" | "geo" | "dated";
  model: "corridors/check" | "fleets/schedule";
  csvType: "sessions" | "grid-headroom";
  spec: PlanningSpec;
  scenario: Scenario | null;
  onSaved: (scenario: Scenario) => void;
};
export type Obj = Record<string, unknown>;
export const pretty = (value: unknown) => JSON.stringify(value, null, 2);
export const roles = [
  ["demand_zones", "Зоны спроса"],
  ["candidate_sites", "Площадки"],
  ["grid_nodes", "Узлы сети"],
  ["travel_edges", "Дорожные связи"],
] as const;

export async function api(path: string, init?: RequestInit) {
  const response = await fetch("/api/workbench/" + path, {
    ...init,
    cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : body?.error || "HTTP " + response.status,
    );
  return body;
}
export function JsonEditor({
  label,
  value,
  setValue,
  rows = 12,
}: {
  label: string;
  value: string;
  setValue: (text: string) => void;
  rows?: number;
}) {
  return (
    <label className="wb-field">
      <span>{label}</span>
      <textarea
        rows={rows}
        spellCheck={false}
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
    </label>
  );
}

export function DatasetList({ datasets }: { datasets: Dataset[] }) {
  if (!datasets.length) return null;
  return (
    <div className="wb-datasets">
      <h3>Версии данных</h3>
      <div className="data-table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Версия</th>
              <th>Источник</th>
              <th>Формат</th>
              <th>SHA-256</th>
              <th>Файл</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((item) => (
              <tr key={item.id}>
                <th>
                  {item.name}
                  <small>{item.id}</small>
                </th>
                <td>{item.source}</td>
                <td>
                  {item.format} · {item.role || "—"}
                </td>
                <td title={item.checksum}>{item.checksum?.slice(0, 12)}…</td>
                <td>
                  {item.format === "csv" && (
                    <a
                      href={"/api/workbench/datasets/" + item.id + "/file"}
                      download
                      aria-label={"Скачать " + item.name}
                    >
                      <Download size={16} />
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
