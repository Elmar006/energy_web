import { randomUUID } from "node:crypto";
import { callBackend, isSignedIn } from "@/lib/server";
import { makeDemo, type Mode } from "@/lib/demo";

export async function POST(request: Request) {
  if (!(await isSignedIn())) return Response.json({ error: "Требуется вход" }, { status: 401 });
  const input = await request.json().catch(() => null);
  const importedScenarioID = input?.scenario_id;
  if (importedScenarioID !== undefined && !/^[0-9a-f-]{36}$/.test(importedScenarioID)) {
    return Response.json({ error: "Неверный ID сценария" }, { status: 422 });
  }
  const mode: Mode = input?.mode;
  const budget = Number(input?.budget);
  const demand = Number(input?.demand);
  if (!importedScenarioID && (!["operator", "city"].includes(mode) || !Number.isFinite(budget) || budget < 1000000 || budget > 50000000 || !Number.isFinite(demand) || demand < 50 || demand > 200)) {
    return Response.json({ error: "Проверьте параметры сценария" }, { status: 422 });
  }
  try {
    let scenarioID = importedScenarioID;
    if (!scenarioID) {
      const scenario = await callBackend("/api/v1/scenarios", {
        method: "POST", body: JSON.stringify({ name: `Демо · ${mode} · ${new Date().toISOString()}`, spec: makeDemo(mode, budget, demand) }),
      });
      if (scenario.status !== 201) return Response.json({ error: scenario.body?.detail || "Не удалось сохранить сценарий" }, { status: 502 });
      scenarioID = scenario.body.id;
    } else {
      const existing = await callBackend(`/api/v1/scenarios/${scenarioID}`);
      if (existing.status !== 200) return Response.json({ error: "Сценарий не найден" }, { status: 404 });
    }
    const run = await callBackend(`/api/v1/scenarios/${scenarioID}/runs`, {
      method: "POST", headers: { "Idempotency-Key": randomUUID() },
      ...(input?.run_spec ? { body: JSON.stringify({ run_spec: input.run_spec }) } : {}),
    });
    if (run.status !== 202) return Response.json({ error: run.body?.detail || "Не удалось запустить расчёт" }, { status: [409, 413, 422].includes(run.status) ? run.status : 502 });
    return Response.json({ run_id: run.body.id, scenario_id: scenarioID, run: run.body }, { status: 202 });
  } catch {
    return Response.json({ error: "Расчётный сервис недоступен" }, { status: 503 });
  }
}
