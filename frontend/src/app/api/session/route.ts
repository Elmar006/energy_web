import { cookies } from "next/headers";
import { isSignedIn, setSession } from "@/lib/server";

export async function GET() {
  return Response.json({ signed_in: await isSignedIn() });
}

export async function POST(request: Request) {
  const data = await request.json().catch(() => null);
  const password = process.env.APP_DEMO_PASSWORD;
  if (!password || typeof data?.password !== "string" || data.password !== password) {
    return Response.json({ error: "Неверный пароль" }, { status: 401 });
  }
  await setSession();
  return Response.json({ signed_in: true });
}

export async function DELETE() {
  (await cookies()).delete("energy_session");
  return Response.json({ signed_in: false });
}
