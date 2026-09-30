import { BodyTooLarge, readLimitedBody } from "../../../../../runtime/body.mjs";
import { isSignedIn } from "@/lib/server";

export const runtime = "nodejs";

type Context = { params: Promise<{ path: string[] }> };
const uuid = "[0-9a-fA-F-]{36}";
const postPaths = [
  /^datasets\/import$/,
  /^scenarios\/from-datasets(?:\/preview)?$/,
  /^scenarios\/from-mobility(?:\/preview)?$/,
  /^artifacts\/demand$/,
  /^corridors\/check$/,
  /^fleets\/schedule$/,
  new RegExp(`^scenarios\/${uuid}\/imports\/(?:sessions|grid-headroom)$`),
  new RegExp(`^runs\/${uuid}\/cancel$`),
];
const getPaths = [
  /^datasets$/,
  new RegExp(`^datasets\/${uuid}\/file$`),
  new RegExp(`^runs\/${uuid}\/events$`),
];

async function forward(request: Request, context: Context, method: "GET" | "POST") {
  if (!(await isSignedIn())) return Response.json({ error: "Требуется вход" }, { status: 401 });
  const { path } = await context.params;
  const target = path.join("/");
  const allowed = method === "GET" ? getPaths : postPaths;
  if (!allowed.some((pattern) => pattern.test(target))) return Response.json({ error: "Маршрут недоступен" }, { status: 404 });
  const limit = target === "artifacts/demand" ? 64 * 1024 * 1024 : target === "datasets/import" || target.includes("/imports/sessions") ? 52 * 1024 * 1024 : 12 * 1024 * 1024;
  const declared = Number(request.headers.get("content-length") || 0);
  if (method === "POST" && declared > limit + 8192) return Response.json({ error: "Файл превышает допустимый размер" }, { status: 413 });
  try {
    const body = method === "POST" ? await readLimitedBody(request, limit + 8192) : undefined;
    if (body && body.byteLength > limit + 8192) return Response.json({ error: "Файл превышает допустимый размер" }, { status: 413 });
    const base = process.env.ENERGY_API_URL || "http://127.0.0.1:58080";
    const headers = new Headers({ Authorization: `Bearer ${process.env.API_TOKEN}` });
    if (body) headers.set("Content-Type", request.headers.get("content-type") || "application/json");
    const lastEventId = request.headers.get("last-event-id");
    if (lastEventId && target.endsWith("/events")) headers.set("Last-Event-ID", lastEventId);
    const signal = target.endsWith("/events") ? request.signal : AbortSignal.any([request.signal, AbortSignal.timeout(target === "fleets/schedule" ? 120_000 : 60_000)]);
    const response = await fetch(`${base}/api/v1/${target}`, { method, headers, body, signal, cache: "no-store" });
    const resultHeaders = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["content-type", "content-disposition", "x-content-sha256"]) {
      const value = response.headers.get(name);
      if (value) resultHeaders.set(name, value);
    }
    return new Response(response.body, { status: response.status, headers: resultHeaders });
  } catch (error) {
    if (error instanceof BodyTooLarge) return Response.json({ error: "Файл превышает допустимый размер" }, { status: 413 });
    return Response.json({ error: "Сервис временно недоступен" }, { status: 503 });
  }
}

export async function GET(request: Request, context: Context) { return forward(request, context, "GET"); }
export async function POST(request: Request, context: Context) { return forward(request, context, "POST"); }
