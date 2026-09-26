"use client";

import Workbench from "@/components/workbench";
import PlanningView from "./planning-view";
import PlanningControls from "./planning-controls";
import WorkspaceHeader from "./workspace-header";
import WorkspaceIntro from "./workspace-intro";
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
    mode,
    setMode,
    budget,
    setBudget,
    demand,
    setDemand,
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

  const firstYear = activeSpec.parameters.years[0] ?? 2027;
  const yearsLabel =
    activeSpec.parameters.years.length > 1
      ? `${firstYear}–${activeSpec.parameters.years.at(-1)}`
      : String(firstYear);

  return (
    <div className="app-shell">
      <WorkspaceHeader
        view={view}
        scenarioId={loadedScenario?.id}
        onLogout={logout}
      />

      <main className="workspace">
        <WorkspaceIntro scenarioName={loadedScenario?.name} />

        <div className="workspace-grid">
          <PlanningControls
            activeSpec={activeSpec}
            loadedScenario={loadedScenario}
            savedScenarios={savedScenarios}
            provenance={provenance}
            mode={mode}
            setMode={setMode}
            budget={budget}
            setBudget={setBudget}
            demand={demand}
            setDemand={setDemand}
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
          />

          <div className="main-column">
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
                  (loadedScenario?.id ?? "demo")
                }
                view={view}
                section={section}
                model={model}
                csvType={csvType}
                spec={activeSpec}
                scenario={loadedScenario}
                onSaved={acceptScenario}
              />
            )}
            {view === "plan" && (
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
