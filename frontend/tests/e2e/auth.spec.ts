import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/** Real backend (fresh database), production build. Serial: one account, two logins, within the real rate limits. */
test.describe.configure({ mode: "serial" });

const email = `e2e-${Date.now()}@example.org`;
const password = "lectures4ever-e2e";
const name = "End To End";

async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.length}`);
}

async function noHorizontalOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
}

async function webStorageIsEmpty(page: Page) {
  return page.evaluate(() => window.localStorage.length === 0 && window.sessionStorage.length === 0 && document.cookie === "");
}

test("GF0A-21 auth screens match the Figma geometry at 1440×900", async ({ page }) => {
  for (const path of ["/signin", "/signup"]) {
    await page.goto(path);
    const brand = page.getByRole("region", { name: "About IntelliStudy" });
    const card = page.getByTestId("auth-card");
    await expect(card).toBeVisible();
    expect((await brand.boundingBox())?.width).toBe(640);
    const box = await card.boundingBox();
    expect(box?.width).toBe(440);
    const style = await card.evaluate((el) => {
      const s = getComputedStyle(el);
      return { padding: s.padding, radius: s.borderTopLeftRadius, gap: s.rowGap };
    });
    expect(style).toEqual({ padding: "40px", radius: "16px", gap: "24px" });
    for (const control of await page.locator("input, button[type=submit]").all()) {
      expect((await control.boundingBox())?.height, path).toBe(44);
    }
    expect((await page.getByRole("button", { name: path === "/signin" ? "Sign in" : "Create account" }).boundingBox())?.width).toBe(358);
    const heading = await page.getByRole("heading", { level: 1 }).boundingBox();
    const firstLabel = await page.locator("form label").first().boundingBox();
    expect(Math.round(firstLabel!.y - (heading!.y + heading!.height)), `${path}: heading to first field`).toBe(24);
  }
  await page.goto("/signin");
  await expect(page.getByText("Study from your own materials.")).toBeVisible();
  await expect(page.getByText("Every claim links to a page, slide or section.")).toBeVisible();
});

test("GF0A-22 accessibility: axe, keyboard order, visible focus, no overflow at 1440 and 720", async ({ page }) => {
  for (const path of ["/signin", "/signup"]) {
    await page.goto(path);
    await expect(page.getByTestId("auth-card")).toBeVisible();
    expect(await seriousViolations(page), path).toEqual([]);
    expect(await noHorizontalOverflow(page), path).toBe(true);
  }
  await page.goto("/signin");
  await expect(page.getByLabel("University email")).toBeVisible();
  const order: string[] = [];
  for (let i = 0; i < 5; i += 1) {
    await page.keyboard.press("Tab");
    order.push(await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      return el?.getAttribute("aria-label") ?? el?.textContent?.trim() ?? el?.getAttribute("type") ?? "";
    }));
    if (i === 0) {
      const outline = await page.evaluate(() => getComputedStyle(document.activeElement as Element).outlineWidth);
      expect(outline).toBe("2px");
    }
  }
  expect(order).toEqual(["Sign in", "Create account", "", "", "Sign in"]);
  await expect(page.getByLabel("Password")).not.toBeFocused();
  await page.setViewportSize({ width: 720, height: 900 }); // 1440 at 200% zoom
  for (const path of ["/signin", "/signup"]) {
    await page.goto(path);
    await expect(page.getByTestId("auth-card")).toBeVisible();
    expect(await noHorizontalOverflow(page), `${path} at 720`).toBe(true);
  }
});

test("GF0A-16 GF0A-19 GF0A-07 sign up lands on the protected landing route (F0-B Dashboard) with nothing in web storage", async ({ page }) => {
  await page.goto("/signup");
  await page.getByLabel("Full name").fill(name);
  await page.getByLabel("University email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1, name: /, End$/ })).toBeVisible();
  await expect(page.getByRole("button", { name: `Account: ${name}` })).toContainText(email);
  expect(await webStorageIsEmpty(page)).toBe(true);
  expect(await seriousViolations(page)).toEqual([]);
});

test("GF0A-14 GF0A-17 GF0A-18 sign in, reload restores the session through the refresh cookie, sign-out protects routes", async ({ page }) => {
  await page.goto("/signin");
  await page.getByLabel("University email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: `Account: ${name}` })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: `Account: ${name}` })).toContainText(email);
  const cookies = await page.context().cookies();
  const refresh = cookies.find((c) => c.name === "__Secure-is_refresh");
  expect(refresh?.httpOnly).toBe(true);
  expect(refresh?.path).toBe("/api/v1/auth");
  expect(await webStorageIsEmpty(page)).toBe(true);

  // GF0A-18: after sign-out (in the account menu since F0-B), the protected route sends the visitor to /signin.
  await page.getByRole("button", { name: `Account: ${name}` }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/signin/);
  await page.goto("/");
  await expect(page).toHaveURL("/signin?next=%2F");
  await expect(page.getByRole("heading", { level: 1, name: "Welcome back" })).toBeVisible();
});

test("GF0A-15 bad credentials show the generic message and stay on the sign-in page", async ({ page }) => {
  await page.goto("/signin");
  await page.getByLabel("University email").fill(email);
  await page.getByLabel("Password").fill("not-the-password-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("auth-card").getByRole("alert")).toHaveText("Invalid email or password.");
  await expect(page).toHaveURL(/\/signin/);
});
