import type { NextConfig } from "next";
const nextConfig: NextConfig = {
  experimental: { proxyClientMaxBodySize: "65mb" },
  output: "standalone", poweredByHeader: false, allowedDevOrigins: ["127.0.0.1"],
  async headers() { return [{ source: "/:path*", headers: [
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    { key: "Content-Security-Policy", value: "frame-ancestors 'none'; base-uri 'self'; object-src 'none'" },
  ] }]; },
};
export default nextConfig;
