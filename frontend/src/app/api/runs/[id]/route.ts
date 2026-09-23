import { callBackend, isSignedIn } from "@/lib/server";

type Context = { params: Promise<{ id: string }> };

export async function GET(_request: Request, context: Context) {
  if (!(await isSignedIn())) return Response.json({ error: "Требуется вход" }, { status: 401 });
  const { id } = await context.params;
  if (!/^[0-9a-f-]{36}$/.test(id)) return Response.json({ error: "Неверный ID" }, { status: 400 });
  try {
    const run = await callBackend(`/api/v1/runs/${id}`);
    if (run.status !== 200) return Response.json({ error: "Расчёт не найден" }, { status: 404 });
    if (run.body.state !== "succeeded") return Response.json({ run: run.body });
    const result = await callBackend(`/api/v1/runs/${id}/results`);
    return Response.json({ run: run.body, result: result.body });
  } catch {
    return Response.json({ error: "Сервис результатов недоступен" }, { status: 503 });
  }
}
