import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser, type BrowserContext, type Page, type Request } from "@playwright/test";
import { ALICE, BOB, PASSWORD } from "./accounts";

/**
 * F0-B end to end (docs/F0B_GATE.md) against the real backend of scripts/e2e-backend.sh: fresh database, processing
 * worker on, real embedding model, real rate limits. Serial, one browser session for Alice (rate limits: 3
 * registrations per hour per IP for the whole run including auth.spec.ts, 5 logins per minute, 20 uploads per hour).
 * Fixtures are generated into a temporary directory by tests/e2e/fixtures/make_fixtures.py; data/uploads is never used.
 */
test.describe.configure({ mode: "serial" });

const REPO = resolve(__dirname, "..", "..", "..");
const COURSE = "Queueing Theory";
const HOSTILE_COURSE = "<script>alert(1)</script>";
const HOSTILE_RENAME = "javascript:alert(1)";
const HOSTILE_FILE = "<img src=x onerror=alert(1)>.pdf";
const WIDTHS = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
  { width: 720, height: 900 },
  { width: 390, height: 844 },
];

let fixtures = "";
let context: BrowserContext;
let page: Page;
let courseUrl = "";
const dialogs: string[] = [];

function python(): string {
  if (process.env.E2E_PYTHON) return process.env.E2E_PYTHON;
  const venv = join(REPO, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

async function seriousViolations(target: Page) {
  const results = await new AxeBuilder({ page: target }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

async function overflowAt(target: Page): Promise<string[]> {
  const failures: string[] = [];
  for (const size of WIDTHS) {
    await target.setViewportSize(size);
    await target.waitForTimeout(100);
    const fits = await target.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
    if (!fits) failures.push(`${size.width}×${size.height}`);
  }
  await target.setViewportSize(WIDTHS[0]!);
  return failures;
}

async function webStorageIsEmpty(target: Page) {
  return target.evaluate(() => window.localStorage.length === 0 && window.sessionStorage.length === 0 && document.cookie === "");
}

function row(target: Page, name: string) {
  return target.getByRole("listitem").filter({ has: target.getByText(name, { exact: true }) });
}

test.beforeAll(async ({ browser }: { browser: Browser }) => {
  fixtures = mkdtempSync(join(tmpdir(), "intellistudy-f0b-fixtures-"));
  execFileSync(python(), [join(__dirname, "fixtures", "make_fixtures.py"), fixtures], { stdio: "inherit" });
  context = await browser.newContext({ viewport: WIDTHS[0], reducedMotion: "reduce" });
  page = await context.newPage();
  page.on("dialog", async (dialog) => {
    dialogs.push(dialog.message());
    await dialog.dismiss();
  });
  // WCAG 2.4.2: once a page has loaded, its <title> must never be missing, also during client navigations (frontend
  // CI run #5 caught Next's streamed metadata removing it for a moment; next.config.ts htmlLimitedBots fixes that).
  await page.addInitScript(() => {
    const gaps: string[] = [];
    (window as unknown as { __titleGaps: string[] }).__titleGaps = gaps;
    new MutationObserver(() => {
      if (document.readyState === "complete" && !document.title) gaps.push(location.pathname + location.search);
    }).observe(document, { subtree: true, childList: true, characterData: true });
  });
});

async function titleGaps(target: Page): Promise<string[]> {
  return target.evaluate(() => (window as unknown as { __titleGaps?: string[] }).__titleGaps ?? []);
}

test.afterAll(async () => {
  await context?.close();
  if (fixtures) rmSync(fixtures, { recursive: true, force: true });
});

test("GF0B-04 GF0B-05 GF0B-01 GF0B-28 a new user lands on the empty Dashboard built from real data only, with no overflow at 1440, 1024, 720 and 390", async () => {
  await page.goto("/signup");
  await page.getByLabel("Full name").fill(ALICE.name);
  await page.getByLabel("University email").fill(ALICE.email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening), Alice$/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No courses yet" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" }).filter({ visible: true });
  await expect(nav.getByRole("link")).toHaveText(["Dashboard", "Courses", "Settings"]);
  await expect(nav.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText(/mastery|streak|recommended|weakest|recent activity/i)).toHaveCount(0);
  expect(await seriousViolations(page), "Dashboard (empty)").toEqual([]);
  expect(await overflowAt(page), "Dashboard overflow").toEqual([]);
});

test("GF0B-07 GF0B-03 GF0B-27 a course is created with the keyboard only and appears on the Dashboard", async () => {
  await page.getByRole("button", { name: "New course" }).first().focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "New course" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Course name")).toBeFocused();
  expect(await seriousViolations(page), "New course dialog").toEqual([]);
  await page.keyboard.press("Escape"); // Escape cancels, focus returns to the trigger
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "New course" }).first()).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog.getByLabel("Course name")).toBeFocused();
  await page.keyboard.type(`  ${COURSE}  `);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/courses\/[0-9a-f-]{36}$/);
  courseUrl = new URL(page.url()).pathname;
  await expect(page.getByRole("heading", { level: 1, name: COURSE })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No materials yet" })).toBeVisible();

  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Courses" }).click();
  await expect(page).toHaveURL("/#courses");
  await expect(page.getByRole("link", { name: new RegExp(COURSE) })).toContainText("No files yet");
});

test("GF0B-15 GF0B-19 GF0B-18 GF0B-28 PDF, PPTX and DOCX upload with progress and reach their terminal states by polling", async () => {
  test.setTimeout(240_000);
  await page.getByRole("link", { name: new RegExp(COURSE) }).click();
  await expect(page).toHaveURL(courseUrl);
  await page.getByRole("link", { name: "Add files" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Add materials" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" }).filter({ visible: true }).getByRole("link", { name: "Courses" })).toHaveAttribute("aria-current", "page");
  expect(await seriousViolations(page), "Upload page").toEqual([]);

  // Keyboard path: "Choose files" opens the file chooser (GF0B-27).
  await page.getByRole("button", { name: "Choose files" }).focus();
  const chooser = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  const files = ["lecture-notes.pdf", "lecture-slides.pptx", "handout.docx", "blank.pdf", "damaged.pdf"];
  await (await chooser).setFiles(files.map((f) => join(fixtures, f)));

  // Choosing files only stages them: one "Selected" row each, nothing sent until "Add these files" (ADD-*).
  for (const name of files) await expect(row(page, name).getByText("Selected", { exact: true })).toBeVisible();
  await expect(page.getByText("Nothing is uploaded until you add the files.")).toBeVisible();
  expect(await seriousViolations(page), "Upload page with staged files").toEqual([]);
  const add = page.getByRole("button", { name: "Add these files" });
  await add.focus();
  await page.keyboard.press("Enter"); // keyboard path for the explicit action
  // Every file accepted: success state, then the course workspace (client navigation), processing visible there.
  await expect(page).toHaveURL(/\/courses\/[0-9a-f-]{36}$/, { timeout: 60_000 });
  await expect(page.getByText("5 files added. Processing has started.").first()).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: COURSE })).toBeVisible();
  await page.getByRole("link", { name: "Add files" }).first().click();
  for (const name of files) await expect(row(page, name)).toHaveCount(1);

  const expected: Record<string, string> = {
    "lecture-notes.pdf": "Indexed",
    "lecture-slides.pptx": "Indexed",
    "handout.docx": "Indexed",
    "blank.pdf": "Empty",
    "damaged.pdf": "Failed",
  };
  for (const [name, tag] of Object.entries(expected)) {
    await expect(row(page, name).getByText(tag, { exact: true })).toBeVisible({ timeout: 180_000 });
  }
  await expect(page.getByText("3 indexed · 0 in progress · 2 need attention")).toBeVisible();
  await expect(row(page, "lecture-slides.pptx")).toContainText("3 slides");
  await expect(row(page, "blank.pdf")).toContainText("This file has no readable text, so there is nothing to index.");
  await expect(row(page, "damaged.pdf")).toContainText("The file appears to be damaged.");
  expect(await seriousViolations(page), "Upload page with rows").toEqual([]);
  expect(await overflowAt(page), "Upload overflow").toEqual([]);
});

test("GF0B-10 GF0B-17 reload shows the persisted server data", async () => {
  await page.reload();
  for (const name of ["lecture-notes.pdf", "lecture-slides.pptx", "handout.docx", "blank.pdf", "damaged.pdf"]) {
    await expect(row(page, name)).toHaveCount(1);
  }
  await expect(page.getByText("3 indexed · 0 in progress · 2 need attention")).toBeVisible();
});

test("GF0B-10 GF0B-22 GF0B-28 the workspace shows real stats and downloads the original file", async () => {
  // Since F1 an Indexed row's "Open" goes to the Summary (as in the prototype); the workspace selects files itself.
  await expect(row(page, "handout.docx").getByRole("link", { name: "Open handout.docx" })).toHaveAttribute("href", /\/documents\/[0-9a-f-]{36}\/summary$/);
  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: COURSE }).click();
  // WCAG 2.4.2 (frontend CI run #5): a client navigation's real RSC response carries the <title> inline, never as a
  // deferred metadata row that would leave the page without a title until it resolves (next.config.ts htmlLimitedBots).
  const navigation = page.waitForResponse((r) => r.request().headers()["rsc"] === "1" && r.url().includes("?file="));
  await page.getByRole("region", { name: "Materials" }).getByRole("link", { name: /handout\.docx/ }).click();
  const payload = await (await navigation).text();
  expect(payload).toContain('"title","0",{"children":"IntelliStudy"}');
  expect(payload, "metadata must not be streamed as a deferred row").not.toContain('{"metadata":');
  await expect(page).toHaveURL(new RegExp(`${courseUrl}\\?file=`));
  await expect(page.getByText("3 of 5")).toBeVisible();
  await expect(page.getByText("2 failed")).toBeVisible();
  const details = page.getByRole("region", { name: "handout.docx" });
  await expect(details).toContainText("Word (.docx)");
  const download = page.waitForEvent("download");
  await details.getByRole("button", { name: "Download" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("handout.docx");
  const saved = await file.path();
  expect(statSync(saved).size).toBe(statSync(join(fixtures, "handout.docx")).size);
  expect(readFileSync(saved).subarray(0, 2).toString()).toBe("PK");
  await expect(page.getByRole("navigation", { name: "Main" }).filter({ visible: true }).getByRole("link", { name: "Courses" })).toHaveAttribute("aria-current", "page");
  expect(await seriousViolations(page), "Workspace").toEqual([]);
  expect(await overflowAt(page), "Workspace overflow").toEqual([]);
});

test("GF0B-20 Retry sends a failed file back to processing and it ends in its real state again", async () => {
  test.setTimeout(120_000);
  const materials = page.getByRole("region", { name: "Materials" });
  const retried = page.waitForResponse((r) => r.url().endsWith("/retry") && r.request().method() === "POST");
  await materials.getByRole("button", { name: "Retry damaged.pdf" }).click();
  expect((await retried).status()).toBe(202);
  await expect(materials.getByRole("listitem").filter({ hasText: "damaged.pdf" }).getByText("Failed", { exact: true })).toBeVisible({ timeout: 90_000 });
});

test("GF0B-21 a document is deleted only after confirmation", async () => {
  const materials = page.getByRole("region", { name: "Materials" });
  await materials.getByRole("link", { name: /blank\.pdf/ }).click();
  await page.getByRole("region", { name: "blank.pdf" }).getByRole("button", { name: "Delete file" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete this file?" });
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  expect(await seriousViolations(page), "Delete file dialog").toEqual([]);
  expect(await titleGaps(page), "the document title is never missing after load").toEqual([]);
  const deleted = page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().includes("/documents/"));
  await dialog.getByRole("button", { name: "Delete file" }).click();
  expect((await deleted).status()).toBe(204);
  await expect(materials.getByText("blank.pdf")).toHaveCount(0);
  await expect(page.getByText("3 of 4")).toBeVisible();
});

test("GF0B-25 F-M4-03 — Frontend Rendering Safety: hostile course and file names stay inert text", async () => {
  test.setTimeout(150_000);
  await page.getByRole("link", { name: "Dashboard", exact: true }).filter({ visible: true }).click();
  await page.getByRole("button", { name: "New course" }).first().click();
  await page.getByLabel("Course name").fill(HOSTILE_COURSE);
  await page.getByRole("button", { name: "Create course" }).click();
  await expect(page.getByRole("heading", { level: 1, name: HOSTILE_COURSE })).toBeVisible();
  await page.getByRole("link", { name: "Add files" }).click();
  await page.getByTestId("file-input").setInputFiles({ name: HOSTILE_FILE, mimeType: "application/pdf", buffer: readFileSync(join(fixtures, "hostile.pdf")) });
  await page.getByRole("button", { name: "Add this file" }).click();
  await expect(page).toHaveURL(/\/courses\/[0-9a-f-]{36}$/, { timeout: 60_000 });
  await page.getByRole("link", { name: "Add files" }).first().click();
  await expect(row(page, HOSTILE_FILE).getByText("Indexed", { exact: true })).toBeVisible({ timeout: 120_000 });
  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: HOSTILE_COURSE }).click();
  await page.getByRole("button", { name: "Rename" }).click();
  await page.getByLabel("Course name").fill(HOSTILE_RENAME);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("heading", { level: 1, name: HOSTILE_RENAME })).toBeVisible();
  await page.getByRole("link", { name: "Dashboard", exact: true }).filter({ visible: true }).click();
  const card = page.getByRole("link", { name: new RegExp(HOSTILE_RENAME.replace(/[()]/g, "\\$&")) });
  await expect(card).toBeVisible();
  expect(await card.getAttribute("href")).toMatch(/^\/courses\/[0-9a-f-]{36}$/);
  expect(await page.locator('img[src="x"], script:not([src]):text("alert")').count()).toBe(0);
  const unsafe = await page.evaluate(() => [...document.querySelectorAll("a")].map((a) => a.getAttribute("href") ?? "").filter((h) => /^\s*javascript:/i.test(h)));
  expect(unsafe).toEqual([]);
  expect(dialogs).toEqual([]);
});

test("GF0B-09 /courses goes to the Dashboard's course list", async () => {
  await page.goto("/courses");
  await expect(page).toHaveURL("/#courses");
  await expect(page.getByRole("heading", { name: "Your courses" })).toBeVisible();
});

test("GF0B-11 another user's course URLs show the same not-found state as a missing course, with nothing leaked", async ({ browser }) => {
  const register = await page.request.post("/api/v1/auth/register", { data: { email: BOB.email, name: BOB.name, password: PASSWORD } });
  expect(register.status()).toBe(201);
  const bobContext = await browser.newContext({ viewport: WIDTHS[0], reducedMotion: "reduce" });
  const bob = await bobContext.newPage();
  try {
    await bob.goto("/signin");
    await bob.getByLabel("University email").fill(BOB.email);
    await bob.getByLabel("Password").fill(PASSWORD);
    await bob.getByRole("button", { name: "Sign in" }).click();
    await expect(bob.getByRole("heading", { name: "No courses yet" })).toBeVisible();
    const texts: string[] = [];
    for (const path of [courseUrl, `${courseUrl}/upload`, "/courses/00000000-0000-4000-8000-000000000000", "/courses/not-an-id"]) {
      await bob.goto(path);
      await expect(bob.getByRole("heading", { level: 1, name: "Course not found" })).toBeVisible();
      texts.push((await bob.getByRole("main").innerText()).trim());
    }
    expect(new Set(texts).size).toBe(1);
    expect(texts[0]).not.toContain(COURSE);
    expect(texts[0]).not.toMatch(/lecture|\.pdf|\.docx|\.pptx/i);
    expect(await seriousViolations(bob), "Not found").toEqual([]);
  } finally {
    await bobContext.close();
  }
});

test("UPL-PROXY a PowerPoint over 10 MB reaches the backend whole through the Next.js proxy; a renamed file never leaves the browser", async () => {
  test.setTimeout(300_000);
  const large = join(fixtures, "large-lecture.pptx");
  expect(statSync(large).size).toBeGreaterThan(10 * 1024 * 1024); // above Next.js's default 10 MB proxy body limit
  await page.goto("/");
  await page.getByRole("link", { name: new RegExp(COURSE.replace(/[()]/g, "\\$&")) }).click();
  await page.getByRole("link", { name: "Add files" }).click();
  const sent: string[] = [];
  const onRequest = (request: Request) => {
    if (request.method() === "POST" && /\/documents$/.test(new URL(request.url()).pathname)) sent.push(request.url());
  };
  page.on("request", onRequest);
  try {
    await page.getByTestId("file-input").setInputFiles([large, join(fixtures, "renamed-video.pptx")]);
    await expect(row(page, "renamed-video.pptx")).toContainText("doesn’t match its extension");
    expect(sent).toHaveLength(0); // staged: nothing sent before the explicit action
    await page.getByRole("button", { name: "Add this file" }).click(); // the renamed file is not counted
    await expect(page).toHaveURL(/\/courses\/[0-9a-f-]{36}$/, { timeout: 120_000 });
    await page.getByRole("link", { name: "Add files" }).first().click();
    await expect(row(page, "large-lecture.pptx").getByText("Indexed", { exact: true })).toBeVisible({ timeout: 240_000 });
    expect(sent).toHaveLength(1); // only the real PowerPoint was uploaded
    expect(await overflowAt(page), "Upload overflow with a large file").toEqual([]);
  } finally {
    page.off("request", onRequest);
  }
});

test("GF0B-13 GF0B-29 courses are deleted after confirmation, the Dashboard ends empty, and web storage holds no token", async () => {
  await page.goto("/");
  for (const name of [HOSTILE_RENAME, COURSE]) {
    await page.getByRole("link", { name: new RegExp(name.replace(/[()]/g, "\\$&")) }).click();
    await page.getByRole("button", { name: "Delete course" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete this course?" });
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
    expect(await seriousViolations(page), "Delete course dialog").toEqual([]);
    await dialog.getByRole("button", { name: "Delete course" }).click();
    await expect(page).toHaveURL("/");
  }
  await expect(page.getByRole("heading", { name: "No courses yet" })).toBeVisible();
  await expect(page.getByText("Course deleted.").first()).toBeVisible();
  expect(await webStorageIsEmpty(page)).toBe(true);
  const refresh = (await context.cookies()).find((c) => c.name === "__Secure-is_refresh");
  expect(refresh?.httpOnly).toBe(true);
  expect(dialogs).toEqual([]);
});
