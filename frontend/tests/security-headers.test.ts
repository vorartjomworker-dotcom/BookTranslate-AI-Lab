import { describe, expect, it } from "vitest";

import nextConfig, { browserSecurityHeaders } from "../next.config";

const expectedHeaders = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Content-Security-Policy": "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
};

describe("browser security headers", () => {
  it("defines the hardened baseline", () => {
    const actual = Object.fromEntries(browserSecurityHeaders.map(({ key, value }) => [key, value]));
    expect(actual).toEqual(expectedHeaders);
  });

  it("applies the headers to every frontend route", async () => {
    expect(nextConfig.headers).toBeTypeOf("function");
    const rules = await nextConfig.headers!();

    expect(rules).toHaveLength(1);
    expect(rules[0]?.source).toBe("/:path*");
    expect(Object.fromEntries(rules[0]?.headers.map(({ key, value }) => [key, value]))).toEqual(expectedHeaders);
  });
});
