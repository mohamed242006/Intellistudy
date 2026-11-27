import { rmSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Browser, type BrowserContext, type Page, type Request } from "@playwright/test";
import { ALICE } from "./accounts";
import { makeFixtures, seriousViolations, signIn } from "./support";

/**
 * The Course Workspace as the primary place to pick materials and act on them, against the isolated backend with the
 * deterministic test provider. Runs after selection.spec.ts and reuses its course "Multi-file study" (four ready files
 * and one failed file), so it stays within the real rate limits. Also the exact single-document summary flow
 * (create → wait → open → reload) and a real failed summary followed by a working retry.
 */
test.describe.configure({ mode: "serial" });

const COURSE = "Multi-file study";
const READY = ["quiz-notes.pdf", "lecture-notes.pdf", "lecture-slides.pptx", "handout.docx"];
const WIDTHS = [360, 768, 1366, 1920];
let fixtures = "";
let context: BrowserContext;
let page: Page;
let workspaceUrl = "";
const posts: { path: string; body: unknown }[] = [];

const materials = (target: Page) => target.getByRole("region", { name: "Materials" });
const box = (target: Page, name: string) => materials(target).getByRole("checkbox", { name: `Select ${name}` });

async function noOverflow(target: Page): Promise<string[]> {
  const bad: string[] = [];
  for (const width of WIDTHS) {
    await target.setViewportSize({ width, height: 900 });
    await target.waitForTimeout(150);
    const px = await target.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (px > 0) bad.push(`${width}px: ${px}px`);
  }
  await target.setViewportSize({ width: 1440, height: 900 });
  return bad;
}

test.beforeAll(async ({ browser }: { browser: Browser }) => {
  fixtures = makeFixtures("intellistudy-ws-fixtures-");
  context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  page = await context.newPage();
  page.on("request", (request: Request) => {
    if (request.method() !== "POST") return;
    const path = new URL(request.url()).pathname;
    if (/\/(summaries|summary|quizzes)$/.test(path)) posts.push({ path, body: request.postDataJSON() });
  });
});

test.afterAll(async () => {
  await context?.close();
  if (fixtures) rmSync(fixtures, { recursive: true, force: true });
});

test("WS-E2E-01 every eligible material has a visible checkbox; preview and selection are separate; Select all takes ready files only", async () => {
  test.setTimeout(120_000);
  await signIn(page, ALICE.email);
  await page.getByRole("link", { name: new RegExp(COURSE) }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: COURSE })).toBeVisible();
  workspaceUrl = new URL(page.url()).pathname;
  for (const name of READY) {
    await expect(box(page, name)).toBeVisible();
    await expect(box(page, name)).toBeEnabled();
  }
  await expect(box(page, "damaged.pdf")).toBeDisabled();
  await expect(page.getByTestId("workspace-count")).toHaveText("0 of 4 files selected");
  // preview one file: it drives the details panel and checks nothing
  await materials(page).getByRole("link", { name: /^Preview lecture\-notes\.pdf/ }).click();
  await expect(materials(page).getByRole("link", { name: /^Preview lecture\-notes\.pdf/ })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("region", { name: "lecture-notes.pdf" })).toBeVisible();
  await expect(page.getByTestId("workspace-count")).toHaveText("0 of 4 files selected");
  // select two from the keyboard
  await box(page, "quiz-notes.pdf").focus();
  await page.keyboard.press("Space");
  await box(page, "lecture-notes.pdf").focus();
  await page.keyboard.press("Space");
  await expect(page.getByTestId("workspace-count")).toHaveText("2 of 4 files selected");
  await expect(page.getByTestId("selection-card").getByRole("heading", { name: "2 files selected" })).toBeVisible();
  await expect(page.getByTestId("select-all")).toHaveJSProperty("indeterminate", true);
  // Select all: ready files only
  await page.getByTestId("select-all").check();
  await expect(page.getByTestId("workspace-count")).toHaveText("4 of 4 files selected");
  await expect(box(page, "damaged.pdf")).not.toBeChecked();
  expect(await seriousViolations(page), "Workspace with a selection").toEqual([]);
  expect(await noOverflow(page), "Workspace with a selection: overflow").toEqual([]);
  await materials(page).getByRole("button", { name: "Clear" }).click();
  await expect(page.getByTestId("workspace-count")).toHaveText("0 of 4 files selected");
});

test("WS-E2E-01b at 360 px the checked-files bar is pinned to the bottom of the screen, not of the page", async () => {
  // with motion ON: the bug was a transform left behind by the page entrance animation
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 360, height: 800 });
  try {
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: COURSE })).toBeVisible();
    await page.waitForTimeout(500); // the 300 ms page entrance has finished
    await box(page, "quiz-notes.pdf").check();
    const bar = page.getByTestId("batch-bar");
    await expect(bar).toHaveAttribute("data-open", "true");
    await page.waitForTimeout(400); // after the page entrance animation
    const rect = await bar.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { bottom: r.bottom, vh: window.innerHeight };
    });
    expect(Math.round(rect.bottom)).toBe(rect.vh);
    await expect(bar.getByRole("button", { name: "Create summary" })).toBeInViewport();
    await box(page, "quiz-notes.pdf").uncheck();
    await expect(bar).toHaveAttribute("data-open", "false");
  } finally {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
  }
});

test("WS-E2E-02 Create combined summary from the workspace sends exactly the two checked ids and opens a working summary", async () => {
  test.setTimeout(180_000);
  await box(page, "quiz-notes.pdf").check();
  await box(page, "handout.docx").check();
  const card = page.getByTestId("selection-card");
  await expect(card.getByRole("heading", { name: "2 files selected" })).toBeVisible();
  posts.length = 0;
  await card.getByRole("button", { name: "Create combined summary" }).click();
  await expect(page).toHaveURL(/\/summaries\/[0-9a-f-]{36}$/);
  const sent = posts.filter((p) => p.path.endsWith("/summaries"));
  expect(sent).toHaveLength(1);
  const ids = (sent[0]!.body as { document_ids: string[] }).document_ids;
  expect(ids).toHaveLength(2);
  await expect(page.getByText("Every statement links to the file and page it came from. Sections are grouped by file.")).toBeVisible({ timeout: 120_000 });
  for (const name of ["quiz-notes.pdf", "handout.docx"]) await expect(page.getByRole("link", { name: `Open ${name}` })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Combined summary")).toBeVisible();
  await expect(page.getByText("Every statement links to the file and page it came from. Sections are grouped by file.")).toBeVisible();
});

test("WS-E2E-03 Create quiz from the workspace: the quiz page starts with the checked files and the quiz lists them", async () => {
  test.setTimeout(180_000);
  await page.goto(workspaceUrl);
  await box(page, "quiz-notes.pdf").check();
  await box(page, "lecture-notes.pdf").check();
  await page.getByTestId("selection-card").getByRole("button", { name: "Create quiz" }).click();
  await expect(page).toHaveURL(/\/quizzes\?from=workspace$/);
  await expect(page.getByRole("checkbox", { name: "quiz-notes.pdf" })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: "lecture-notes.pdf" })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: "damaged.pdf, Processing failed" })).toBeDisabled();
  await page.getByLabel("Number of questions").fill("6");
  posts.length = 0;
  await page.getByRole("button", { name: "Create quiz from 2 files" }).click();
  await expect(page).toHaveURL(/\/quizzes\/[0-9a-f-]{36}$/);
  const sent = posts.filter((p) => p.path.endsWith("/quizzes"));
  expect(sent).toHaveLength(1);
  expect((sent[0]!.body as { document_ids: string[] }).document_ids).toHaveLength(2); // never the failed file
  await expect(page.getByRole("button", { name: "Start quiz" })).toBeVisible({ timeout: 120_000 });
  const sources = page.locator("p", { hasText: "2 SOURCE FILES:" });
  await expect(sources).toContainText("quiz-notes.pdf");
  await expect(sources).toContainText("lecture-notes.pdf");
  await expect(sources).not.toContainText("damaged.pdf");
});

test("WS-E2E-04 single file, no summary yet: Create summary (never Open summary) → wait → open → reload still loads", async () => {
  test.setTimeout(180_000);
  await page.goto(workspaceUrl);
  await materials(page).getByRole("link", { name: /^Preview lecture\-slides\.pptx/ }).click();
  const details = page.getByRole("region", { name: "lecture-slides.pptx" });
  const create = details.getByRole("button", { name: "Create summary" });
  await expect(create).toBeVisible();
  await expect(details.getByRole("link", { name: "Open summary" })).toHaveCount(0);
  await create.click();
  await expect(page).toHaveURL(/\/documents\/[0-9a-f-]{36}\/summary$/);
  await expect(page.getByText("Every statement links to the page it came from. Select a badge to see the exact passage.")).toBeVisible({ timeout: 120_000 });
  await page.reload();
  await expect(page.getByText("Every statement links to the page it came from. Select a badge to see the exact passage.")).toBeVisible();
  await page.goto(`${workspaceUrl}?file=${new URL(page.url()).pathname.split("/")[4]}`);
  await expect(page.getByRole("region", { name: "lecture-slides.pptx" }).getByRole("link", { name: "Open summary" })).toBeVisible();
});

test("WS-E2E-05 a failed summary shows its real, safe reason; Retry summary then works", async () => {
  test.setTimeout(300_000);
  await page.goto(workspaceUrl);
  await page.getByRole("link", { name: "Add files" }).first().click();
  await page.getByTestId("file-input").setInputFiles([join(fixtures, "flaky-summary.pdf")]);
  await page.getByRole("button", { name: "Add this file" }).click();
  await expect(page).toHaveURL(workspaceUrl, { timeout: 60_000 });
  await expect(box(page, "flaky-summary.pdf")).toBeEnabled({ timeout: 180_000 }); // ready
  await materials(page).getByRole("link", { name: /^Preview flaky\-summary\.pdf/ }).click();
  const details = page.getByRole("region", { name: "flaky-summary.pdf" });
  await details.getByRole("button", { name: "Create summary" }).click();
  await expect(page).toHaveURL(/\/documents\/[0-9a-f-]{36}\/summary$/);
  await expect(page.getByText("The summary couldn’t be written")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText("The AI service is unavailable right now. Try again later.")).toBeVisible();
  await expect(page.getByText(/Check your connection/)).toHaveCount(0);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Every statement links to the page it came from. Select a badge to see the exact passage.")).toBeVisible({ timeout: 120_000 });
});

test("WS-E2E-06 reduced motion switches entrance animations off; without it they run", async ({ browser }) => {
  await page.goto(workspaceUrl);
  await expect(page.getByRole("heading", { level: 1, name: COURSE })).toBeVisible();
  await page.locator(".motion-enter").first().waitFor();
  expect(await page.evaluate(() => getComputedStyle(document.querySelector(".motion-enter")!).animationName)).toBe("none");
  const moving = await browser.newContext({ reducedMotion: "no-preference" });
  try {
    const other = await moving.newPage();
    await other.goto("/signin");
    await other.locator(".motion-enter").first().waitFor();
    expect(await other.evaluate(() => getComputedStyle(document.querySelector(".motion-enter")!).animationName)).toBe("is-enter");
  } finally {
    await moving.close();
  }
});
