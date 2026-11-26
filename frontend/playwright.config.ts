import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against a real backend (scripts/e2e-backend.sh, port 8100) and a production build of the frontend
 * (port 3100) whose /api/v1 rewrite points at that backend. The browser uses http://localhost:3100, which is the
 * origin the backend's CSRF check allows for this run.
 */
/** Explicit ports for the isolated run; never the development backend (8000). */
const PORTS = { backend: "8100", llm: "8101", frontend: "3100" } as const;
const FRONTEND = `http://localhost:${PORTS.frontend}`;
const BACKEND = `http://127.0.0.1:${PORTS.backend}`;

export default defineConfig({
  testDir: "./tests/e2e",
  globalSetup: "./tests/e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1, // one backend, real rate limits: keep the auth calls sequential and few
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: FRONTEND, trace: "retain-on-failure", viewport: { width: 1440, height: 900 } },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: "bash scripts/e2e-backend.sh",
      env: { E2E_BACKEND_PORT: PORTS.backend, E2E_LLM_PORT: PORTS.llm, E2E_FRONTEND_ORIGIN: FRONTEND },
      url: `${BACKEND}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 }, // lets the script stop the stub and delete its temp dir
    },
    {
      command: "bash scripts/e2e-frontend.sh",
      env: { INTELLISTUDY_API_ORIGIN: BACKEND, E2E_FRONTEND_PORT: PORTS.frontend },
      url: `${FRONTEND}/signin`,
      reuseExistingServer: false,
      timeout: 300_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
    },
  ],
});
