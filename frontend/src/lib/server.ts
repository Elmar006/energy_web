import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

const cookieName = "energy_session";

function signature(expires: string) {
  const secret = process.env.API_TOKEN;
  if (!secret || secret.length < 24) throw new Error("API_TOKEN is not configured");
  return createHmac("sha256", secret).update(expires).digest("hex");
}

export async function isSignedIn() {
  const value = (await cookies()).get(cookieName)?.value;
  if (!value) return false;
  const [expires, mac] = value.split(".");
  if (!expires || !mac || Number(expires) <= Date.now()) return false;
  const expected = Buffer.from(signature(expires), "hex");
  const actual = Buffer.from(mac, "hex");
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

export async function setSession() {
  const expires = String(Date.now() + 12 * 60 * 60 * 1000);
  (await cookies()).set(cookieName, `${expires}.${signature(expires)}`, {
    httpOnly: true, sameSite: "strict", secure: process.env.APP_COOKIE_SECURE === "true",
    path: "/", maxAge: 12 * 60 * 60,
  });
}

export async function callBackend(path: string, init?: RequestInit) {
  const base = process.env.ENERGY_API_URL || "http://127.0.0.1:58080";
  const response = await fetch(`${base}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${process.env.API_TOKEN}`,
      ...init?.headers,
    },
  });
  const text = await response.text();
  return { status: response.status, body: text ? JSON.parse(text) : null };
}
