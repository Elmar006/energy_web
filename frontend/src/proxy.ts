import { NextResponse, type NextRequest } from "next/server";
import { trustedMutation } from "../runtime/policy.mjs";

export function proxy(request: NextRequest) {
  if (!["GET", "HEAD", "OPTIONS"].includes(request.method) &&
      !trustedMutation(request.headers.get("origin"), request.url, process.env, request.headers.get("host"))) {
    return NextResponse.json({ error: "Запрос отклонён: недоверенный Origin" }, { status: 403 });
  }
  return NextResponse.next();
}

export const config = { matcher: "/api/:path*" };
