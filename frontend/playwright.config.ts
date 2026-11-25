import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against a real backend (scripts/e2e-backend.sh, port 8100) and a production build of the frontend
 * (port 3100) whose /api/v1 rewrite points at that backend. The browser uses http://localhost:3100, which is the
 * origin the backend's CSRF check allows for this run.
 */
const FRONTEND = "http://localhost:3100";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1, // one backend, real rate limits: keep the auth calls sequential and few
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: FRONTEND, trace: "retain-on-failure", viewport: { width: 1440, height: 900 } },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: "bash scripts/e2e-backend.sh",
      url: "http://127.0.0.1:8100/api/v1/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npx next build && npx next start --port 3100",
      env: { INTELLISTUDY_API_ORIGIN: "http://127.0.0.1:8100", NEXT_TELEMETRY_DISABLED: "1" },
      url: `${FRONTEND}/signin`,
      reuseExistingServer: false,
      timeout: 300_000,
    },
  ],
});
