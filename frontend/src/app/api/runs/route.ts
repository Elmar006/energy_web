import { BodyTooLarge, readLimitedJson } from "../../../../runtime/body.mjs";
import { randomUUID } from "node:crypto";
import { callBackend, isSignedIn } from "@/lib/server";

export async function POST(request: Request) {
  if (!(await isSignedIn())) return Response.json({ error: "Требуется вход" }, { status: 401 });
  let input;
  try { input = await readLimitedJson(request, 16384); }
  catch (error) { return Response.json({ error: "Некорректный или слишком большой JSON" }, { status: error instanceof BodyTooLarge ? 413 : 400 }); }
  const importedScenarioID = input?.scenario_id;
  if (typeof importedScenarioID !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(importedScenarioID)) {
    return Response.json({ error: "Для запуска требуется ID сохранённого сценария" }, { status: 422 });
  }
  try {
    const scenarioID = importedScenarioID;
    const existing = await callBackend(`/api/v1/scenarios/${scenarioID}`);
    if (existing.status !== 200) return Response.json({ error: "Сценарий недоступен" }, { status: existing.status === 404 ? 404 : 502 });
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
