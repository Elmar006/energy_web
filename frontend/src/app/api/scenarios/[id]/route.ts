import { callBackend, isSignedIn } from "@/lib/server";

type Context = { params: Promise<{ id: string }> };

export async function GET(_request: Request, context: Context) {
  if (!(await isSignedIn())) return Response.json({ error: "Требуется вход" }, { status: 401 });
  const { id } = await context.params;
  if (!/^[0-9a-f-]{36}$/.test(id)) return Response.json({ error: "Неверный ID сценария" }, { status: 400 });
  try {
    const response = await callBackend(`/api/v1/scenarios/${id}`);
    if (response.status !== 200) return Response.json({ error: "Сценарий не найден" }, { status: 404 });
    return Response.json(response.body, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "Сервис сценариев недоступен" }, { status: 503 });
  }
}
