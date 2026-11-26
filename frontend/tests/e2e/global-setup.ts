/** One id per Playwright run, inherited by every worker, so spec files share the run's accounts (tests/e2e/accounts.ts). */
export default function globalSetup(): void {
  process.env.E2E_RUN_ID ??= String(Date.now());
}
