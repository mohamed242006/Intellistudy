import type { NextConfig } from "next";
import { PROXY_BODY_LIMIT_BYTES } from "./features/upload/limits";

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
  // Render metadata (the document <title>) blocking, in <head>, for every user agent instead of streaming it after the
  // page. With streamed metadata, client navigations inside a dynamic route (for example ?file= in the workspace)
  // removed the <title> for a moment, a WCAG 2.4.2 gap that axe caught on the slower CI runner (frontend run #5).
  htmlLimitedBots: /.*/,
  experimental: {
    // The /api/v1 rewrite below proxies request bodies through a copy that Next.js 15.5 cuts off at this size (default
    // 10 MB, node_modules/next/dist/server/body-streams.js). Uploads above 10 MB reached the backend truncated and were
    // refused ("Request body exceeded 10MB ... Only the first 10MB will be available"). One file per request, so the
    // limit is the backend's per-file limit plus multipart framing (features/upload/limits.ts). In Next.js 16 this
    // option is renamed `proxyClientMaxBodySize`; 15.5 only reads `middlewareClientMaxBodySize`.
    middlewareClientMaxBodySize: PROXY_BODY_LIMIT_BYTES,
  },
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiOrigin()}/api/v1/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
