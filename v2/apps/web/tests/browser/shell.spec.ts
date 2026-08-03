import {expect, Page, test} from "@playwright/test";

const curatorId = "55555555-5555-4555-8555-555555555555";

async function mockShell(page: Page, authenticated = true) {
  await page.route("**/api/auth/me", route => authenticated
    ? route.fulfill({json: {
      user_id: curatorId, email: "curator@rtrobotics.com",
      display_name: "RtR Curator", roles: ["curator"],
    }})
    : route.fulfill({status: 401, json: {
      error: {code: "authentication_required", message: ""}, request_id: "req-0",
    }}));
  await page.route("**/api/status", route => route.fulfill({json: {
    ok: true, status: "ready",
  }}));
  await page.route("**/api/ask/conversations**", route => route.fulfill({json: {
    items: [], next_cursor: null,
  }}));
}

test("shell shows one topbar, six nav areas, and active state follows navigation", async ({page}) => {
  await mockShell(page);
  await page.goto("/ask");
  await expect(page.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  const nav = page.getByRole("navigation", {name: "Điều hướng chính"});
  for (const [name, href] of [
    ["Hỏi", "/ask"], ["Tệp", "/files"], ["Tài liệu", "/documents"],
    ["Tri thức", "/knowledge-ops?view=research"],
    ["Vận hành", "/knowledge-ops"], ["Quản trị", "/admin"],
  ] as const) {
    await expect(nav.getByRole("link", {name})).toHaveAttribute("href", href);
  }
  await expect(nav.getByRole("link", {name: "Hỏi"}))
    .toHaveAttribute("aria-current", "page");
  await expect(page.getByText("RtR Curator")).toBeVisible();
  await nav.getByRole("link", {name: "Quản trị"}).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("heading", {level: 1, name: "Quản trị"})).toBeVisible();
  await expect(nav.getByRole("link", {name: "Quản trị"}))
    .toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", {name: "Hỏi"}))
    .not.toHaveAttribute("aria-current", "page");
  await page.screenshot({path: "test-results/tip011-shell-desktop.png", fullPage: true});
});

test("skip link is the first tab stop and moves focus to the work surface", async ({page}) => {
  await mockShell(page);
  await page.goto("/ask");
  await expect(page.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", {name: "Bỏ qua tới nội dung chính"});
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("main");
});

test("F6 / Shift+F6 cycle focus between navigation and work surface", async ({page}) => {
  await mockShell(page);
  await page.goto("/ask");
  await expect(page.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  await page.keyboard.press("F6");
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("shell-nav");
  await page.keyboard.press("F6");
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("main");
  await page.keyboard.press("Shift+F6");
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("shell-nav");
});

test("mobile drawer opens, closes on Escape, and closes after navigating", async ({page}) => {
  await mockShell(page);
  await page.setViewportSize({width: 360, height: 800});
  await page.goto("/ask");
  const nav = page.getByRole("navigation", {name: "Điều hướng chính"});
  // The premium sidebar is the drawer; the `open` class lives on its container.
  const sidebar = page.locator("#pc-sidebar");
  const toggle = page.getByRole("button", {name: "Điều hướng", exact: true});
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(sidebar).toHaveClass(/open/);
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(sidebar).not.toHaveClass(/open/);
  await toggle.click();
  await nav.getByRole("link", {name: "Quản trị"}).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("heading", {level: 1, name: "Quản trị"})).toBeVisible();
  await expect(sidebar).not.toHaveClass(/open/);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({path: "test-results/tip011-shell-mobile.png", fullPage: true});
});

test("language switch persists across navigation and reload via cookie only", async ({page}) => {
  await mockShell(page);
  await page.goto("/ask");
  await expect(page.locator("html")).toHaveAttribute("lang", "vi");
  await page.getByRole("button", {name: "EN"}).click();
  await expect(page.getByRole("heading", {level: 1, name: "Ask"})).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.getByRole("navigation", {name: "Primary navigation"})
    .getByRole("link", {name: "Admin"}).click();
  await expect(page.getByRole("heading", {level: 1, name: "Administration"}))
    .toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", {level: 1, name: "Administration"}))
    .toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  const cookie = (await page.context().cookies())
    .find(item => item.name === "rtr_locale");
  expect(cookie?.value).toBe("en");
  const storage = await page.evaluate(
    () => localStorage.length + sessionStorage.length,
  );
  expect(storage).toBe(0);
});

test("the legacy root URL redirects to the files workspace under the shell", async ({page}) => {
  // TIP-011 Task 3 inverted the redirect: /files IS the workspace, "/" redirects.
  await mockShell(page, false);
  await page.goto("/");
  await expect(page).toHaveURL(/\/files$/);
  await expect(page.getByRole("heading", {level: 1, name: "Tệp"})).toBeVisible();
});

test("anonymous shell keeps placeholders public and offers company sign-in", async ({page}) => {
  await mockShell(page, false);
  await page.goto("/ask");
  await expect(page.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  await expect(page.getByRole("link", {name: "Đăng nhập công ty"})).toBeVisible();
});
