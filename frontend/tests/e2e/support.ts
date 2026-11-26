/** Shared E2E helpers for the F2 spec (the F0/F1 specs keep their own copies unchanged). */
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { PASSWORD } from "./accounts";

const REPO = resolve(__dirname, "..", "..", "..");
export const WIDTHS = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
  { width: 720, height: 900 },
  { width: 390, height: 844 },
];

/** Generate the deterministic fixtures into a new temporary directory (never data/uploads). */
export function makeFixtures(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  const venv = join(REPO, ".venv", "bin", "python");
  const python = process.env.E2E_PYTHON ?? (existsSync(venv) ? venv : "python3");
  execFileSync(python, [join(__dirname, "fixtures", "make_fixtures.py"), dir], { stdio: "inherit" });
  return dir;
}

export async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

export async function overflowAt(page: Page): Promise<string[]> {
  const failures: string[] = [];
  for (const size of WIDTHS) {
    await page.setViewportSize(size);
    await page.waitForTimeout(150);
    if (!(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth))) failures.push(`${size.width}×${size.height}`);
  }
  await page.setViewportSize(WIDTHS[0]!);
  return failures;
}

export async function noInjectedMarkup(page: Page) {
  return page.evaluate(() => ({
    elements: document.querySelectorAll('img[src="x"], main script, main iframe').length,
    unsafeLinks: [...document.querySelectorAll("a")].map((a) => a.getAttribute("href") ?? "").filter((h) => /^\s*javascript:/i.test(h)).length,
  }));
}

/** Sign in through the form; when the shared real login limit answers, wait the stated time and try once more. */
export async function signIn(page: Page, email: string) {
  await page.goto("/signin");
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await page.getByLabel("University email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    const courses = page.getByRole("heading", { name: "Your courses" });
    const limited = page.getByTestId("auth-card").getByText(/^Too many attempts\. Try again in (\d+) seconds\.$/);
    await expect(courses.or(limited)).toBeVisible();
    if (await courses.isVisible()) return;
    const seconds = Number((await limited.textContent())?.match(/(\d+)/)?.[1] ?? 60);
    await page.waitForTimeout((seconds + 1) * 1000);
  }
  await expect(page.getByRole("heading", { name: "Your courses" })).toBeVisible();
}
