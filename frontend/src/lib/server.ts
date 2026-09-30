import { cookies } from "next/headers";
import { issueSession, verifySession, validateRuntime } from "../../runtime/policy.mjs";

const cookieName = "energy_session";
export async function isSignedIn() {
  const value = (await cookies()).get(cookieName)?.value;
  if (!value) return false;
  return verifySession(value, validateRuntime(process.env).secret);
}
export async function setSession() {
  const config = validateRuntime(process.env);
  (await cookies()).set(cookieName, issueSession(config.secret), {
    httpOnly: true, sameSite: "strict", secure: config.production || process.env.APP_COOKIE_SECURE === "true",
    path: "/", maxAge: 12 * 60 * 60,
  });
}
export async function callBackend(path: string, init?: RequestInit) {
  const base = process.env.ENERGY_API_URL || "http://127.0.0.1:58080";
  const timeout = AbortSignal.timeout(path === "/api/v1/fleets/schedule" ? 120_000 : 30_000);
  const response = await fetch(`${base}${path}`, {
    ...init, signal: init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout, cache: "no-store",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${process.env.API_TOKEN}`, ...init?.headers },
  });
  const text = await response.text();
  return { status: response.status, body: text ? JSON.parse(text) : null };
}
