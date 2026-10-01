import { BodyTooLarge, readLimitedJson } from "../../../../runtime/body.mjs";
import { cookies } from "next/headers";
import { isSignedIn, setSession } from "@/lib/server";
import { LoginLimiter, passwordsEqual, validateRuntime } from "../../../../runtime/policy.mjs";
const limiter = new LoginLimiter();

export async function GET() {
  return Response.json({ signed_in: await isSignedIn() });
}

export async function POST(request: Request) {
  if (!limiter.consume()) return Response.json({ error: "Слишком много попыток входа. Подождите минуту." }, { status: 429, headers: { "Retry-After": "60" } });
  let data;
  try { data = await readLimitedJson(request, 4096); }
  catch (error) { return Response.json({ error: "Некорректный или слишком большой JSON" }, { status: error instanceof BodyTooLarge ? 413 : 400 }); }
  const { password } = validateRuntime(process.env);
  if (typeof data?.password !== "string" || data.password.length > 1024 || !passwordsEqual(data.password, password)) {
    return Response.json({ error: "Неверный пароль" }, { status: 401 });
  }
  await setSession();
  return Response.json({ signed_in: true });
}

export async function DELETE() {
  (await cookies()).delete("energy_session");
  return Response.json({ signed_in: false });
}
