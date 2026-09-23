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
  const length = Number(request.headers.get("content-length") || 0);
  if (length > 2_000_000) return Response.json({ error: "Файл больше 2 МБ" }, { status: 413 });
  const raw = await request.text();
  if (raw.length > 2_000_000) return Response.json({ error: "Файл больше 2 МБ" }, { status: 413 });
  let input: { name?: unknown; spec?: unknown };
  try { input = JSON.parse(raw); }
  catch { return Response.json({ error: "Файл должен содержать корректный JSON" }, { status: 400 }); }
  if (typeof input.name !== "string" || !input.name.trim() || input.name.length > 120 || !input.spec || typeof input.spec !== "object") {
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
