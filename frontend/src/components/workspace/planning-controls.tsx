"use client";

import {
  Activity,
  ArrowRight,
  Check,
  Clock3,
  Info,
  MapPinned,
  Zap,
} from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import type { Mode } from "@/lib/demo";
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
  activeSpec: PlanningSpec;
  loadedScenario: SavedScenario | null;
  savedScenarios: ScenarioSummary[];
  provenance: { observed: number; derived: number; assumed: number };
  mode: Mode;
  setMode: Setter<Mode>;
  budget: number;
  setBudget: Setter<number>;
  demand: number;
  setDemand: Setter<number>;
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
  savedScenarios,
  provenance,
  mode,
  setMode,
  budget,
  setBudget,
  demand,
  setDemand,
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
  chooseScenario,
  uploadScenario,
  start,
}: Props) {
  return (
    <aside className="control-panel" aria-labelledby="scenario-title">
      <div className="panel-heading">
        <span className="panel-icon">
          <Activity size={18} />
        </span>
        <div>
          <p className="eyebrow">ПАРАМЕТРЫ РАСЧЁТА</p>
          <h2 id="scenario-title">Новый сценарий</h2>
        </div>
      </div>
      <div className="scenario-source">
        <label htmlFor="saved-scenario">Источник расчёта</label>
        <Select
          id="saved-scenario"
          label="Источник расчёта"
          value={loadedScenario?.id ?? ""}
          onValueChange={(value) => void chooseScenario(value)}
          options={[
            { value: "", label: "Демо · синтетические данные" },
            ...savedScenarios
              .filter((item) => !item.name.startsWith("Демо ·"))
              .map((item) => ({ value: item.id, label: item.name })),
          ]}
        />
        <label className="file-label" htmlFor="scenario-file">
          Загрузить PlanningInput JSON
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
      </div>
      {loadedScenario && (
        <div className="source-quality">
          <strong>Качество входа</strong>
          <span>
            Записи спроса, площадок и узлов: {provenance.observed} наблюдаемых ·{" "}
            {provenance.derived} вычисленных · {provenance.assumed}{" "}
            предположенных.
          </span>
          {activeSpec.datasets?.length ? (
            <ul>
              {activeSpec.datasets.map((dataset) => (
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
      {!loadedScenario && (
        <>
          <fieldset className="mode-options">
            <legend>Цель планирования</legend>
            <label className={`mode-card ${mode === "city" ? "active" : ""}`}>
              <input
                type="radio"
                name="mode"
                checked={mode === "city"}
                onChange={() => setMode("city")}
              />
              <span className="mode-text">
                <strong>Для города</strong>
                <small>Максимальная доступность зарядки</small>
              </span>
              <span className="mode-check">
                {mode === "city" && <Check size={15} />}
              </span>
            </label>
            <label
              className={`mode-card ${mode === "operator" ? "active" : ""}`}
            >
              <input
                type="radio"
                name="mode"
                checked={mode === "operator"}
                onChange={() => setMode("operator")}
              />
              <span className="mode-text">
                <strong>Для оператора</strong>
                <small>Экономика развития сети</small>
              </span>
              <span className="mode-check">
                {mode === "operator" && <Check size={15} />}
              </span>
            </label>
          </fieldset>
          <div className="field-block">
            <label htmlFor="budget">
              Инвестиционный бюджет <strong>{budget} млн ₽</strong>
            </label>
            <input
              id="budget"
              type="range"
              min="1"
              max="50"
              step="1"
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
            />
            <div className="range-ends">
              <span>1 млн ₽</span>
              <span>50 млн ₽</span>
            </div>
          </div>
          <div className="field-block">
            <label htmlFor="demand">
              Уровень спроса <strong>{demand}%</strong>
            </label>
            <input
              id="demand"
              type="range"
              min="50"
              max="200"
              step="10"
              value={demand}
              onChange={(e) => setDemand(Number(e.target.value))}
            />
            <div className="range-ends">
              <span>50%</span>
              <span>200%</span>
            </div>
          </div>
        </>
      )}
      <div className="parameters-summary">
        <div>
          <Clock3 size={17} />
          <span>Горизонт</span>
          <strong>{yearsLabel}</strong>
        </div>
        <div>
          <Zap size={17} />
          <span>Энергосеть</span>
          <strong>
            {plural(activeSpec.grid_nodes.length, "узел", "узла", "узлов")}
          </strong>
        </div>
        <div>
          <MapPinned size={17} />
          <span>Площадки</span>
          <strong>
            {plural(
              activeSpec.sites.length,
              "кандидат",
              "кандидата",
              "кандидатов",
            )}
          </strong>
        </div>
      </div>
      <details className="run-settings">
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
      </details>
      <button
        className="primary-button run-button"
        onClick={start}
        disabled={
          submitting ||
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
          : "Все мощности, цены и спрос в пилоте — сценарные предположения."}{" "}
        Результат не является согласованием подключения.
      </p>
    </aside>
  );
}
