import { rmSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Browser, type BrowserContext, type Page, type Request } from "@playwright/test";
import { ALICE } from "./accounts";
import { makeFixtures, seriousViolations, signIn } from "./support";

/**
 * Add materials with "Add these files", then one combined Summary and one multi-file Quiz from selected files, against
 * the isolated backend with the deterministic test provider. Runs after quiz.spec.ts with the run's existing account.
 */
test.describe.configure({ mode: "serial" });

const COURSE = "Multi-file study";
const TARGET_WIDTHS = [360, 768, 1366, 1920];
// quiz-notes.pdf holds the facts the deterministic test model writes questions from (tests/e2e/fixtures)
const READY = ["quiz-notes.pdf", "lecture-notes.pdf", "lecture-slides.pptx", "handout.docx"];
let fixtures = "";
let context: BrowserContext;
let page: Page;
let workspaceUrl = "";
const posts: { path: string; body: unknown }[] = [];

async function noOverflow(target: Page): Promise<string[]> {
  const bad: string[] = [];
  for (const width of TARGET_WIDTHS) {
    await target.setViewportSize({ width, height: 900 });
    await target.waitForTimeout(150);
    const px = await target.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (px > 0) bad.push(`${width}px: ${px}px`);
  }
  await target.setViewportSize({ width: 1440, height: 900 });
  return bad;
}

test.beforeAll(async ({ browser }: { browser: Browser }) => {
  fixtures = makeFixtures("intellistudy-sel-fixtures-");
  context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  page = await context.newPage();
  page.on("request", (request: Request) => {
    if (request.method() !== "POST") return;
    const path = new URL(request.url()).pathname;
    if (/\/(summaries|quizzes)$/.test(path)) posts.push({ path, body: request.postDataJSON() });
  });
});

test.afterAll(async () => {
  await context?.close();
  if (fixtures) rmSync(fixtures, { recursive: true, force: true });
});

test("ADD-E2E several materials are added with “Add these files” and the page moves on to the course", async () => {
  test.setTimeout(300_000);
  await signIn(page, ALICE.email);
  await page.getByRole("button", { name: "New course" }).first().click();
  await page.getByLabel("Course name").fill(COURSE);
  await page.getByRole("button", { name: "Create course" }).click();
  await expect(page.getByRole("heading", { level: 1, name: COURSE })).toBeVisible();
  workspaceUrl = new URL(page.url()).pathname;
  await page.getByRole("link", { name: /Add files|Upload files/ }).first().click();
  await page.getByTestId("file-input").setInputFiles([...READY, "damaged.pdf"].map((f) => join(fixtures, f)));
  const add = page.getByRole("button", { name: "Add these files" });
  await expect(add).toBeVisible();
  await add.click();
  await expect(page).toHaveURL(workspaceUrl, { timeout: 60_000 }); // client navigation after every file was accepted
  await expect(page.getByText("5 files added. Processing has started.").first()).toBeVisible();
  await page.getByRole("link", { name: "Add files" }).first().click();
  await expect(page.getByText("4 indexed · 0 in progress · 1 need attention")).toBeVisible({ timeout: 180_000 });
});

test("SEL-E2E Select all picks ready files only; one combined summary is grounded in all of them", async () => {
  test.setTimeout(180_000);
  await page.goto(workspaceUrl);
  await page.getByRole("link", { name: "Summaries" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Create a summary" })).toBeVisible();
  const failed = page.getByRole("checkbox", { name: "damaged.pdf, Processing failed" });
  await expect(failed).toBeDisabled();
  await expect(page.getByRole("button", { name: "Create summary from 0 files" })).toBeDisabled();
  expect(await noOverflow(page), "Create summary: overflow").toEqual([]);
  await page.getByRole("checkbox", { name: "Select all ready files" }).check();
  await expect(page.getByTestId("selected-count")).toHaveText("4 files selected");
  await expect(failed).not.toBeChecked();
  expect(await seriousViolations(page), "Create summary").toEqual([]);
  expect(await noOverflow(page), "Create summary (selected): overflow").toEqual([]);
  await page.getByRole("button", { name: "Create summary from 4 files" }).click();
  await expect(page).toHaveURL(/\/summaries\/[0-9a-f-]{36}$/);
  const sent = posts.filter((p) => p.path.endsWith("/summaries"));
  expect(sent).toHaveLength(1);
  expect((sent[0]!.body as { document_ids: string[] }).document_ids).toHaveLength(4); // the failed file is never sent
  await expect(page.getByText("Every statement links to the file and page it came from. Sections are grouped by file.")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText("Combined summary")).toBeVisible();
  for (const name of READY) {
    await expect(page.getByRole("link", { name: `Open ${name}` })).toBeVisible();
  }
  const groups = page.locator("section[aria-label]").filter({ has: page.getByRole("heading", { level: 2 }) });
  expect(await groups.count()).toBeGreaterThanOrEqual(2); // content from more than one file, each under its file
  expect(await seriousViolations(page), "Combined summary").toEqual([]);
  expect(await noOverflow(page), "Combined summary: overflow").toEqual([]);
});

test("SEL-E2E a quiz from two selected files: generated, taken, submitted and reviewed with per-question sources", async () => {
  test.setTimeout(240_000);
  await page.goto(`${workspaceUrl}/quizzes`);
  await expect(page.getByRole("heading", { level: 1, name: "Quizzes" })).toBeVisible();
  await page.getByRole("checkbox", { name: "quiz-notes.pdf" }).check();
  await page.getByRole("checkbox", { name: "lecture-notes.pdf" }).check();
  await expect(page.getByRole("checkbox", { name: "Select all ready files" })).toHaveJSProperty("indeterminate", true);
  await page.getByLabel("Number of questions").fill("6");
  expect(await noOverflow(page), "Quiz form: overflow").toEqual([]);
  await page.getByRole("button", { name: "Create quiz from 2 files" }).click();
  await expect(page).toHaveURL(/\/quizzes\/[0-9a-f-]{36}$/);
  const quizPost = posts.filter((p) => p.path.endsWith("/quizzes"));
  expect(quizPost).toHaveLength(1);
  expect((quizPost[0]!.body as { document_ids: string[] }).document_ids).toHaveLength(2);
  await expect(page.getByRole("button", { name: "Start quiz" })).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText(/2 SOURCE FILES:/)).toBeVisible();
  await page.getByRole("button", { name: "Start quiz" }).click();
  await expect(page).toHaveURL(/\/attempts\/[0-9a-f-]{36}$/);
  const total = Number(((await page.getByText(/^Question 1 of \d+$/).textContent()) ?? "").match(/of (\d+)/)![1]);
  for (let i = 1; i <= total; i += 1) {
    await page.getByRole("group").first().getByRole("radio").first().check();
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();
    if (i < total) await page.getByRole("button", { name: "Next question" }).click();
  }
  await page.getByRole("button", { name: "Finish quiz" }).first().click();
  await page.getByRole("dialog", { name: "Submit your answers?" }).getByRole("button", { name: "Submit answers" }).click();
  await expect(page).toHaveURL(/\/attempts\/[0-9a-f-]{36}\/review$/);
  await expect(page.getByRole("heading", { level: 2, name: /^\d+ of \d+ correct$/ })).toBeVisible();
  const review = await page.locator("main").innerText();
  expect(review).toContain("EVIDENCE");
  expect(review).not.toContain("lecture-slides.pptx"); // only the selected files are sources
  expect(review).not.toContain("handout.docx");
  expect(review).not.toContain("damaged.pdf");
  expect(await seriousViolations(page), "Multi-file quiz review").toEqual([]);
  expect(await noOverflow(page), "Review: overflow").toEqual([]);
});
