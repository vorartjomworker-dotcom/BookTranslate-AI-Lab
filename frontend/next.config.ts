import type { NextConfig } from "next";

import { validatePublicApiBaseUrl } from "./config/public-api-url";

export const publicApiBaseUrl = validatePublicApiBaseUrl(process.env.NEXT_PUBLIC_API_URL);

export const browserSecurityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  {
    key: "Content-Security-Policy",
    value: "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
  },
] as const;

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [...browserSecurityHeaders],
      },
    ];
  },
};

export default nextConfig;
