import { BodyTooLarge, readLimitedJson } from "../../../../runtime/body.mjs";
import { callBackend, isSignedIn } from "@/lib/server";

export async function GET() {
  if (!(await isSignedIn())) return Response.json({ error: "Требуется вход" }, { status: 401 });
  try {
    const response = await callBackend("/api/v1/scenarios");
    if (response.status !== 200) return Response.json({ error: "Не удалось загрузить сценарии" }, { status: 502 });
    return Response.json(response.body, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "Сервис сценариев недоступен" }, { status: 503 });
  }
}

export async function POST(request: Request) {
  if (!(await isSignedIn())) return Response.json({ error: "Требуется вход" }, { status: 401 });
  let input: { name?: unknown; spec?: unknown };
  try { input = await readLimitedJson(request, 2_000_000); }
  catch (error) { return Response.json({ error: "Файл слишком велик или содержит некорректный JSON" }, { status: error instanceof BodyTooLarge ? 413 : 400 }); }
  if (!input || typeof input !== "object" || Array.isArray(input) || typeof input.name !== "string" || !input.name.trim() || input.name.length > 120 || !input.spec || typeof input.spec !== "object" || Array.isArray(input.spec)) {
    return Response.json({ error: "Нужны название и объект расчётного сценария" }, { status: 422 });
  }
  try {
    const response = await callBackend("/api/v1/scenarios", {
      method: "POST", body: JSON.stringify({ name: input.name.trim(), spec: input.spec }),
    });
    if (response.status !== 201) {
      return Response.json({ error: response.body?.detail || "Сценарий не прошёл проверку" }, { status: response.status === 422 ? 422 : 502 });
    }
    return Response.json(response.body, { status: 201 });
  } catch {
    return Response.json({ error: "Сервис сценариев недоступен" }, { status: 503 });
  }
}
