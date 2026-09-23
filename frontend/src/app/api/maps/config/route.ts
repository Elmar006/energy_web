import { isSignedIn } from "@/lib/server";

export async function GET() {
  if (!(await isSignedIn())) return Response.json({ error: "Требуется вход" }, { status: 401 });
  const apiKey = process.env.YANDEX_MAPS_API_KEY?.trim();
  return Response.json({ configured: Boolean(apiKey), ...(apiKey ? { apiKey } : {}) },
    { headers: { "Cache-Control": "no-store" } });
}
