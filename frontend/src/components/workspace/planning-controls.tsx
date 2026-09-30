"use client";

import {
  Activity,
  ArrowRight,
  Clock3,
  Info,
  MapPinned,
  Zap,
} from "lucide-react";
import { useState, type Dispatch, type SetStateAction } from "react";
import type { PlanningSpec } from "@/lib/planning";
import Select from "@/components/ui/select";
import {
  plural,
  type Result,
  type Run,
  type SavedScenario,
  type ScenarioSummary,
} from "./result-model";

type RunMode = "default" | "validation" | "improvement";
type Setter<T> = Dispatch<SetStateAction<T>>;

type Props = {
  activeSpec: PlanningSpec | null;
  loadedScenario: SavedScenario | null;
  savedScenarios: ScenarioSummary[];
  provenance: { observed: number; derived: number; assumed: number };
  yearsLabel: string;
  runMode: RunMode;
  setRunMode: Setter<RunMode>;
  seedCount: number;
  setSeedCount: Setter<number>;
  simulationDays: number;
  setSimulationDays: Setter<number>;
  minEnergy: string;
  setMinEnergy: Setter<string>;
  maxWait: string;
  setMaxWait: Setter<string>;
  submitting: boolean;
  runId: string | null;
  run: Run | null;
  result: Result | null;
  uploading: boolean;
  chooseScenario: (id: string) => Promise<void>;
  uploadScenario: (file: File) => Promise<void>;
  start: () => Promise<void>;
};

export default function PlanningControls({
  activeSpec,
  loadedScenario,
  provenance,
  yearsLabel,
  runMode,
  setRunMode,
  seedCount,
  setSeedCount,
  simulationDays,
  setSimulationDays,
  minEnergy,
  setMinEnergy,
  maxWait,
  setMaxWait,
  submitting,
  runId,
  run,
  result,
  uploading,
  uploadScenario,
  start,
}: Props) {
  const [expandedResult, setExpandedResult] = useState<Result | null>(null);
  const collapsed = Boolean(result) && expandedResult !== result;
  return (
    <aside className="control-panel" aria-labelledby="scenario-title">
      <div className="panel-heading">
        <span className="panel-icon">
          <Activity size={18} />
        </span>
        <div>
          <p className="eyebrow">ПАРАМЕТРЫ РАСЧЁТА</p>
          <h2 id="scenario-title">{loadedScenario ? "Условия запуска" : "Настроить сценарий"}</h2>
        </div>
        {result && <button type="button" className="parameters-toggle secondary-button compact-button" aria-controls="planning-parameters-body" aria-expanded={!collapsed} onClick={() => setExpandedResult(collapsed ? result : null)}>{collapsed ? "Развернуть" : "Свернуть"}</button>}
      </div>
      <div id="planning-parameters-body" className={collapsed ? "parameters-body controls-closed" : "parameters-body"}>
      <details className="scenario-source source-import">
        <summary>Импорт готового сценария</summary>
        <label className="file-label" htmlFor="scenario-file">
          Файл сценария · JSON
        </label>
        <input
          id="scenario-file"
          className="file-input"
          type="file"
          accept=".json,application/json"
          disabled={uploading}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void uploadScenario(file);
            event.currentTarget.value = "";
          }}
        />
        <small>
          {uploading
            ? "Проверяем и сохраняем…"
            : "Площадки, спрос, сеть, тарифы и происхождение данных проверяются перед сохранением."}
        </small>
      </details>
      {loadedScenario && (
        <div className="source-quality">
          <strong>Качество входа</strong>
          <span>
            Записи спроса, площадок и узлов: {provenance.observed} наблюдаемых ·{" "}
            {provenance.derived} вычисленных · {provenance.assumed}{" "}
            предположенных.
          </span>
          {activeSpec?.datasets?.length ? (
            <ul>
              {activeSpec?.datasets.map((dataset) => (
                <li key={dataset.sha256}>
                  <strong>
                    {dataset.name} · {dataset.kind}
                  </strong>
                  <span>{dataset.source}</span>
                  <code>SHA-256 {dataset.sha256.slice(0, 12)}…</code>
                </li>
              ))}
            </ul>
          ) : (
            <span>
              Манифест исходных файлов не указан. Смотрите происхождение у
              объектов в JSON.
            </span>
          )}
        </div>
      )}
      {activeSpec && <div className="parameters-summary">
        <div>
          <Clock3 size={17} />
          <span>Горизонт</span>
          <strong>{yearsLabel}</strong>
        </div>
        <div>
          <Zap size={17} />
          <span>Энергосеть</span>
          <strong>
            {activeSpec ? plural(activeSpec.grid_nodes.length, "узел", "узла", "узлов") : "—"}
          </strong>
        </div>
        <div>
          <MapPinned size={17} />
          <span>Площадки</span>
          <strong>
            {activeSpec ? plural(
              activeSpec.sites.length,
              "кандидат",
              "кандидата",
              "кандидатов",
            ) : "—"}
          </strong>
        </div>
      </div>}
      {activeSpec && <details className="run-settings">
        <summary>Настройки проверки расчёта</summary>
        <div className="run-setting-field">
          Режим
          <Select
            label="Режим"
            value={runMode}
            onValueChange={(value) => setRunMode(value as typeof runMode)}
            options={[
              { value: "default", label: "Базовый · 3 seed" },
              { value: "validation", label: "Итоговая проверка" },
              { value: "improvement", label: "Подбор + итоговая проверка" },
            ]}
          />
        </div>
        {runMode !== "default" && (
          <>
            <label>
              Итоговые seed · 30–100
              <input
                type="number"
                min={30}
                max={100}
                value={seedCount}
                onChange={(event) => setSeedCount(Number(event.target.value))}
              />
            </label>
            <label>
              Длительность · дни
              <input
                type="number"
                min={1}
                max={14}
                value={simulationDays}
                onChange={(event) =>
                  setSimulationDays(Number(event.target.value))
                }
              />
            </label>
            <label>
              Мин. обслуженной энергии · %
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={minEnergy}
                onChange={(event) => setMinEnergy(event.target.value)}
                placeholder="Без порога"
              />
            </label>
            <label>
              Макс. p95 ожидания · мин
              <input
                type="number"
                min={0}
                value={maxWait}
                onChange={(event) => setMaxWait(event.target.value)}
                placeholder="Без порога"
              />
            </label>
            <small>
              {runMode === "improvement"
                ? "Подбор ведётся на seed 1001–1003; итоговая приёмка — на отдельном потоке."
                : "Порог проверяется по каждому году и сценарию в SimPy."}
            </small>
          </>
        )}
      </details>}
      <button
        className="primary-button run-button"
        onClick={start}
        disabled={
          !activeSpec || !loadedScenario || submitting ||
          (runId !== null &&
            run?.state !== "succeeded" &&
            run?.state !== "failed" &&
            run?.state !== "cancelled")
        }
      >
        {submitting
          ? "Запускаем…"
          : runId && !result && run?.state !== "failed"
            ? "Идёт расчёт…"
            : "Рассчитать план"}
        <ArrowRight size={18} />
      </button>
      <p className="panel-disclaimer">
        <Info size={15} />{" "}
        {loadedScenario
          ? "Происхождение записей задаётся автором файла; техническая проверка формата не подтверждает достоверность исходных данных."
          : "Данные не загружены. Расчёт требует явно сохранённого входа."}{" "}
        Результат не является согласованием подключения.
      </p>
      </div>
    </aside>
  );
}
