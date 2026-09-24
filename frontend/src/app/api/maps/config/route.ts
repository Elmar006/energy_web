import { isSignedIn } from "@/lib/server";

export async function GET() {
  if (!(await isSignedIn())) return Response.json({ error: "Требуется вход" }, { status: 401 });
  const apiKey = process.env.DGIS_MAPGL_API_KEY?.trim();
  const styleId = process.env.DGIS_MAP_STYLE_ID?.trim();
  return Response.json({ configured: Boolean(apiKey), ...(apiKey ? { apiKey } : {}),
    ...(styleId ? { styleId } : {}) },
    { headers: { "Cache-Control": "no-store" } });
}
