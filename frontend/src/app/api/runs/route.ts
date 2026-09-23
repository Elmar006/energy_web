import { randomUUID } from "node:crypto";
import { callBackend, isSignedIn } from "@/lib/server";
import { makeDemo, type Mode } from "@/lib/demo";

export async function POST(request: Request) {
  if (!(await isSignedIn())) return Response.json({ error: "Требуется вход" }, { status: 401 });
  const input = await request.json().catch(() => null);
  const mode: Mode = input?.mode;
  const budget = Number(input?.budget);
  const demand = Number(input?.demand);
  if (!["operator", "city"].includes(mode) || !Number.isFinite(budget) || budget < 1000000 || budget > 50000000 || !Number.isFinite(demand) || demand < 50 || demand > 200) {
    return Response.json({ error: "Проверьте параметры сценария" }, { status: 422 });
  }
  try {
    const scenario = await callBackend("/api/v1/scenarios", {
      method: "POST", body: JSON.stringify({ name: `Демо · ${mode} · ${new Date().toISOString()}`, spec: makeDemo(mode, budget, demand) }),
    });
    if (scenario.status !== 201) return Response.json({ error: "Не удалось сохранить сценарий" }, { status: 502 });
    const run = await callBackend(`/api/v1/scenarios/${scenario.body.id}/runs`, {
      method: "POST", headers: { "Idempotency-Key": randomUUID() },
    });
    if (run.status !== 202) return Response.json({ error: "Не удалось запустить расчёт" }, { status: 502 });
    return Response.json({ run_id: run.body.id, scenario_id: scenario.body.id }, { status: 202 });
  } catch {
    return Response.json({ error: "Расчётный сервис недоступен" }, { status: 503 });
  }
}
