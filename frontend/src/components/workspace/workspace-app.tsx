"use client";

import Workbench from "@/components/workbench";
import PlanningView from "./planning-view";
import PlanningControls from "./planning-controls";
import WorkspaceHeader from "./workspace-header";
import Select from "@/components/ui/select";
import { Database } from "lucide-react";
import PlanningEmpty from "./planning-empty";
import LoginPanel from "./login-panel";
import { useWorkspace } from "./workspace-state";

type WorkspaceView = "plan" | "data" | "mobility" | "models";
type DataSection = "editor" | "csv" | "geo" | "dated";
type ModelPath = "corridors/check" | "fleets/schedule";

type Props = {
  view: WorkspaceView;
  section?: DataSection;
  model?: ModelPath;
  csvType?: "sessions" | "grid-headroom";
};

export default function WorkspaceApp({
  view,
  section = "editor",
  model = "corridors/check",
  csvType = "sessions",
}: Props) {
  const {
    signedIn,
    password,
    setPassword,
    savedScenarios,
    loadedScenario,
    uploading,
    runId,
    run,
    result,
    error,
    submitting,
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
    activeSpec,
    provenance,
    login,
    logout,
    start,
    cancelRun,
    acceptScenario,
    chooseScenario,
    uploadScenario,
  } = useWorkspace();
  if (signedIn === null)
    return (
      <main className="screen-centered">
        <p>Загружаем рабочее пространство…</p>
      </main>
    );
  if (!signedIn) {
    return (
      <LoginPanel
        password={password}
        onPasswordChange={setPassword}
        onSubmit={login}
        error={error}
      />
    );
  }

  const selectedScenario = activeSpec ? loadedScenario : null;
  const firstYear = activeSpec?.parameters.years[0];
  const yearsLabel =
    activeSpec && activeSpec.parameters.years.length > 1
      ? `${firstYear}–${activeSpec.parameters.years.at(-1)}`
      : firstYear === undefined ? "—" : String(firstYear);

  return (
    <div className="app-shell engineering-shell">
      <WorkspaceHeader
        view={view}
        scenarioId={selectedScenario?.id}
        onLogout={logout}
      />

      <main className="workspace" id="workspace-main" tabIndex={-1}>
        <div className="workspace-context">
          <div><span className="context-kicker">{view === "plan" ? "Планирование" : view === "data" ? "Подготовка данных" : view === "mobility" ? "Транспортный спрос" : "Специальные расчёты"}</span>
          <h1>{view === "plan" ? "Развитие зарядной сети" : view === "data" ? "Данные и сценарии" : view === "mobility" ? "Спрос из поездок" : model === "fleets/schedule" ? "Транспортный парк" : "Транспортный коридор"}</h1>
          <p>{view === "plan" ? "Размещение, инвестиции и проверка работы сети" : view === "data" ? "Подготовьте проверяемый вход и сохраните его версию" : view === "mobility" ? "Свяжите поездки и стоянки с потребностью в зарядке" : "Проверка отдельной транспортной задачи"}</p></div>
          <div className="context-source"><label htmlFor="workspace-scenario">Источник расчёта</label>
          <Select id="workspace-scenario" label="Источник расчёта" value={selectedScenario?.id ?? ""} onValueChange={(value) => void chooseScenario(value)} options={[
            { value: "", label: "Данные не выбраны" },
            ...(selectedScenario ? [{ value: selectedScenario.id, label: selectedScenario.name }] : []),
            ...savedScenarios.filter(item => item.id !== selectedScenario?.id).map(item => ({ value: item.id, label: item.name })),
          ]} />
          <span className="context-quality"><Database size={13} aria-hidden="true" />{selectedScenario ? `${provenance.observed} наблюдаемых · ${provenance.derived} вычисленных · ${provenance.assumed} предположенных` : "Загрузите исходные данные или выберите сохранённую версию"}</span></div>
        </div>
        {(view !== "plan" || !activeSpec) && error && <div className="error-banner" role="alert">{error}</div>}

        <div className={view === "plan" ? `workspace-grid${activeSpec ? "" : " workspace-start"}` : "workspace-wide"}>
          {view === "plan" && !activeSpec && <PlanningEmpty />}
          {view === "plan" && <PlanningControls
            activeSpec={activeSpec}
            loadedScenario={selectedScenario}
            savedScenarios={savedScenarios}
            provenance={provenance}
            yearsLabel={yearsLabel}
            runMode={runMode}
            setRunMode={setRunMode}
            seedCount={seedCount}
            setSeedCount={setSeedCount}
            simulationDays={simulationDays}
            setSimulationDays={setSimulationDays}
            minEnergy={minEnergy}
            setMinEnergy={setMinEnergy}
            maxWait={maxWait}
            setMaxWait={setMaxWait}
            submitting={submitting}
            runId={runId}
            run={run}
            result={result}
            uploading={uploading}
            chooseScenario={chooseScenario}
            uploadScenario={uploadScenario}
            start={start}
          />}

          <div className="main-column" hidden={view === "plan" && !activeSpec}>
            {view !== "plan" && (
              <Workbench
                key={
                  view +
                  ":" +
                  section +
                  ":" +
                  model +
                  ":" +
                  csvType +
                  ":" +
                  (selectedScenario?.id ?? "empty")
                }
                view={view}
                section={section}
                model={model}
                csvType={csvType}
                spec={activeSpec}
                scenario={selectedScenario}
                onSaved={acceptScenario}
              />
            )}
            {view === "plan" && activeSpec && (
              <PlanningView
                activeSpec={activeSpec}
                result={result}
                run={run}
                runId={runId}
                error={error}
                provenance={provenance}
                onCancel={cancelRun}
              />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
