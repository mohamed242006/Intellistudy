import type { NextConfig } from "next";

/**
 * The browser talks to one origin: /api/v1/* is rewritten to the FastAPI backend, so the refresh cookie
 * (HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth) and the CSRF header work without cross-origin requests
 * (FRONTEND_IMPLEMENTATION_PLAN.md section 1).
 *
 * INTELLISTUDY_API_ORIGIN is a server-side setting (never NEXT_PUBLIC_): the backend origin, without a path.
 * Rewrites are resolved when the server starts (`next dev`) or at build time (`next build`).
 */
function apiOrigin(): string {
  // An end-to-end build must name its throwaway backend; it never falls back to the development backend (F1 gate).
  if (process.env.INTELLISTUDY_E2E === "1" && !process.env.INTELLISTUDY_API_ORIGIN) {
    throw new Error("INTELLISTUDY_API_ORIGIN must be set for an end-to-end build");
  }
  const raw = process.env.INTELLISTUDY_API_ORIGIN ?? "http://127.0.0.1:8000";
  const url = new URL(raw);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("INTELLISTUDY_API_ORIGIN must be an http(s) origin");
  }
  return url.origin;
}

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiOrigin()}/api/v1/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
