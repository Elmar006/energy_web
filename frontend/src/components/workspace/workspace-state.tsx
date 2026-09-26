"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import type { Mode } from "@/lib/demo";
import { makeDemo } from "@/lib/demo";
import {
  isPlanningSpec,
  provenanceSummary,
  type PlanningSpec,
} from "@/lib/planning";
import {
  type Result,
  type Run,
  type SavedScenario,
  type ScenarioSummary,
} from "./result-model";

function returnPath() {
  const next = new URLSearchParams(window.location.search).get("next");
  return next?.startsWith("/") && !next.startsWith("//") ? next : "/plan";
}

function useWorkspaceController() {
  const router = useRouter();
  const pathname = usePathname();
  const routeRunId = /^\/runs\/([0-9a-f-]{36})$/.exec(pathname)?.[1] ?? null;
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<Mode>("city");
  const [budget, setBudget] = useState(10);
  const [demand, setDemand] = useState(100);
  const [savedScenarios, setSavedScenarios] = useState<ScenarioSummary[]>([]);
  const [loadedScenario, setLoadedScenario] = useState<SavedScenario | null>(
    null,
  );
  const [uploading, setUploading] = useState(false);
  const [runId, setRunId] = useState<string | null>(routeRunId);
  const [run, setRun] = useState<Run | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [runMode, setRunMode] = useState<
    "default" | "validation" | "improvement"
  >("default");
  const [seedCount, setSeedCount] = useState(30);
  const [simulationDays, setSimulationDays] = useState(3);
  const [minEnergy, setMinEnergy] = useState("");
  const [maxWait, setMaxWait] = useState("");

  useEffect(() => {
    fetch("/api/session")
      .then((r) => r.json())
      .then((v) => {
        const active = Boolean(v.signed_in);
        setSignedIn(active);
        if (!active && window.location.pathname !== "/login") {
          router.replace(
            "/login?next=" +
              encodeURIComponent(
                window.location.pathname + window.location.search,
              ),
          );
        } else if (active && window.location.pathname === "/login") {
          router.replace(returnPath());
        }
      })
      .catch(() => {
        setSignedIn(false);
        if (window.location.pathname !== "/login") router.replace("/login");
      });
  }, [router]);

  useEffect(() => {
    if (!signedIn) return;
    fetch("/api/scenarios", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : []))
      .then(setSavedScenarios)
      .catch(() => setSavedScenarios([]));
  }, [signedIn]);

  useEffect(() => {
    if (!signedIn || routeRunId) return;
    const scenarioId = new URLSearchParams(window.location.search).get(
      "scenario",
    );
    if (!scenarioId || !/^[0-9a-f-]{36}$/.test(scenarioId)) return;
    if (loadedScenario?.id === scenarioId) return;
    fetch(`/api/scenarios/${scenarioId}`, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((scenario) => {
        if (scenario && isPlanningSpec(scenario.spec)) {
          setLoadedScenario({
            id: scenario.id,
            name: scenario.name,
            spec: scenario.spec,
          });
        }
      })
      .catch(() => setError("Сценарий не удалось открыть"));
  }, [signedIn, routeRunId, pathname, loadedScenario?.id]);

  useEffect(() => {
    if (!routeRunId || routeRunId === runId) return;
    const timer = window.setTimeout(() => {
      setRunId(routeRunId);
      setRun(null);
      setResult(null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [routeRunId, runId]);

  const demoSpec = useMemo(
    () => makeDemo(mode, budget * 1_000_000, demand),
    [mode, budget, demand],
  );
  const activeSpec: PlanningSpec = loadedScenario?.spec ?? demoSpec;
  const provenance = provenanceSummary(activeSpec);

  const refresh = useCallback(async () => {
    if (!runId || !signedIn) return;
    const response = await fetch(`/api/runs/${runId}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      setError(payload.error || "Не удалось получить результат");
      return;
    }
    setRun(payload.run);
    if (payload.result) setResult(payload.result);
    if (payload.run.state === "failed")
      setError(payload.run.error_detail || "Расчёт завершился ошибкой");
  }, [runId, signedIn]);

  useEffect(() => {
    if (
      !runId ||
      !signedIn ||
      result ||
      run?.state === "failed" ||
      run?.state === "cancelled"
    )
      return;
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [runId, signedIn, result, run?.state, refresh]);

  useEffect(() => {
    if (
      !runId ||
      !signedIn ||
      result ||
      run?.state === "failed" ||
      run?.state === "cancelled"
    )
      return;
    const events = new EventSource("/api/workbench/runs/" + runId + "/events");
    const update = () => void refresh();
    for (const name of ["running", "succeeded", "failed", "cancelled"])
      events.addEventListener(name, update);
    events.onmessage = update;
    return () => events.close();
  }, [runId, signedIn, result, run?.state, refresh]);

  useEffect(() => {
    if (
      !signedIn ||
      !run?.scenario_id ||
      loadedScenario?.id === run.scenario_id
    )
      return;
    let cancelled = false;
    fetch(`/api/scenarios/${run.scenario_id}`, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((scenario) => {
        if (!cancelled && scenario && isPlanningSpec(scenario.spec)) {
          setLoadedScenario({
            id: scenario.id,
            name: scenario.name,
            spec: scenario.spec,
          });
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [signedIn, run?.scenario_id, loadedScenario?.id]);

  async function login(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    const response = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!response.ok) {
      setError("Неверный пароль доступа");
      return;
    }
    setSignedIn(true);
    setPassword("");
    router.replace(returnPath());
  }

  async function logout() {
    await fetch("/api/session", { method: "DELETE" });
    setSignedIn(false);
    setResult(null);
    setRun(null);
    setRunId(null);
    setLoadedScenario(null);
    router.replace("/login");
  }

  async function start() {
    setSubmitting(true);
    setError("");
    setResult(null);
    setRun(null);
    try {
      const requirements = {
        schema_version: "service-v1",
        ...(minEnergy.trim()
          ? { min_energy_fraction: Number(minEnergy) / 100 }
          : {}),
        ...(maxWait.trim()
          ? { max_mean_seed_p95_wait_minutes: Number(maxWait) }
          : {}),
        min_seeds_per_condition: 30,
      };
      if (
        runMode !== "default" &&
        (seedCount < 30 ||
          seedCount > 100 ||
          simulationDays < 1 ||
          simulationDays > 14 ||
          (minEnergy && (Number(minEnergy) < 0 || Number(minEnergy) > 100)) ||
          (maxWait && Number(maxWait) < 0))
      )
        throw new Error("Проверьте seed, дни и пороги обслуживания");
      if (runMode === "improvement" && !minEnergy.trim() && !maxWait.trim())
        throw new Error(
          "Для подбора варианта нужен хотя бы один порог обслуживания",
        );
      const runSpec =
        runMode === "default"
          ? undefined
          : {
              schema_version:
                runMode === "improvement" ? "run-spec-v2" : "run-spec-v1",
              mode: "validation",
              simulation_seeds: Array.from(
                { length: seedCount },
                (_, index) => index,
              ),
              simulation_days: simulationDays,
              ...(minEnergy.trim() || maxWait.trim()
                ? { service_requirements: requirements }
                : {}),
              ...(runMode === "improvement"
                ? {
                    development_seeds: [1001, 1002, 1003],
                    max_improvement_iterations: 3,
                  }
                : {}),
            };
      const response = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(loadedScenario
            ? { scenario_id: loadedScenario.id }
            : { mode, budget: budget * 1_000_000, demand }),
          ...(runSpec ? { run_spec: runSpec } : {}),
        }),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "Не удалось запустить расчёт");
      setRunId(payload.run_id);
      router.push(`/runs/${payload.run_id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Ошибка запуска");
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelRun() {
    if (!runId) return;
    try {
      const response = await fetch("/api/workbench/runs/" + runId + "/cancel", {
        method: "POST",
      });
      const body = await response.json();
      if (!response.ok)
        throw new Error(body.detail || body.error || "Отмена недоступна");
      await refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Не удалось отменить расчёт",
      );
    }
  }

  function acceptScenario(scenario: SavedScenario) {
    if (!scenario?.id || !isPlanningSpec(scenario.spec))
      throw new Error("Сервис вернул неполный сценарий");
    setLoadedScenario(scenario);
    setSavedScenarios((items) => [
      {
        id: scenario.id,
        name: scenario.name,
        sha256: "",
        created_at: new Date().toISOString(),
      },
      ...items.filter((item) => item.id !== scenario.id),
    ]);
    setRunId(null);
    setRun(null);
    setResult(null);
    setError("");
    router.push(`/plan?scenario=${scenario.id}`);
  }

  async function chooseScenario(id: string) {
    setError("");
    if (!id) {
      setLoadedScenario(null);
      setRunId(null);
      setRun(null);
      setResult(null);
      router.push("/plan");
      return;
    }
    try {
      const response = await fetch(`/api/scenarios/${id}`, {
        cache: "no-store",
      });
      const scenario = await response.json();
      if (!response.ok || !isPlanningSpec(scenario.spec))
        throw new Error("Сохранённый сценарий повреждён или недоступен");
      setLoadedScenario({
        id: scenario.id,
        name: scenario.name,
        spec: scenario.spec,
      });
      setRunId(null);
      setRun(null);
      setResult(null);
      router.push(`/plan?scenario=${id}`);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Не удалось открыть сценарий",
      );
    }
  }

  async function uploadScenario(file: File) {
    setError("");
    setUploading(true);
    try {
      if (file.size > 2_000_000) throw new Error("Файл больше 2 МБ");
      const parsed = JSON.parse(await file.text());
      const spec = parsed?.spec ?? parsed;
      const name =
        typeof parsed?.name === "string"
          ? parsed.name
          : file.name.replace(/\.json$/i, "");
      const response = await fetch("/api/scenarios", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, spec }),
      });
      const scenario = await response.json();
      if (!response.ok)
        throw new Error(scenario.error || "Сценарий не прошёл проверку");
      if (!isPlanningSpec(scenario.spec))
        throw new Error("Сохранённый сценарий не удалось прочитать");
      setLoadedScenario({
        id: scenario.id,
        name: scenario.name,
        spec: scenario.spec,
      });
      setSavedScenarios((items) => [
        {
          id: scenario.id,
          name: scenario.name,
          sha256: scenario.sha256,
          created_at: new Date().toISOString(),
        },
        ...items,
      ]);
      setRunId(null);
      setRun(null);
      setResult(null);
      router.push(`/plan?scenario=${scenario.id}`);
    } catch (caught) {
      setError(
        caught instanceof SyntaxError
          ? "Файл должен содержать корректный JSON"
          : caught instanceof Error
            ? caught.message
            : "Ошибка загрузки",
      );
    } finally {
      setUploading(false);
    }
  }

  return {
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
  };
}

const WorkspaceContext = createContext<ReturnType<
  typeof useWorkspaceController
> | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const state = useWorkspaceController();
  return (
    <WorkspaceContext.Provider value={state}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const state = useContext(WorkspaceContext);
  if (!state) throw new Error("WorkspaceProvider отсутствует");
  return state;
}
