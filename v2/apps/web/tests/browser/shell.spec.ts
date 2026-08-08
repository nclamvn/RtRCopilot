import {expect, Page, test} from "@playwright/test";
import {pilotReadiness} from "./support/mocks";

const curatorId = "55555555-5555-4555-8555-555555555555";

async function mockShell(page: Page, authenticated = true, roles = ["admin"]) {
  await page.route("**/api/auth/me", route => authenticated
    ? route.fulfill({json: {
      user_id: curatorId, email: `${roles[0]}@rtrobotics.com`,
      display_name: roles[0] === "admin" ? "RtR Admin" : "RtR Staff", roles,
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
  // The Ask page treats an authorization failure from this capability probe
  // as session loss. Keep shell-only tests hermetic instead of allowing an
  // unmocked request to whichever API happens to be running locally.
  await page.route("**/api/governance/research/scope", route => route.fulfill({json: {
    allowed: false,
  }}));
  await page.route("**/api/governance/admin/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/jobs/health")) return route.fulfill({json: {
      computed_at: "2026-08-04T08:00:00Z", families: [],
    }});
    if (path.endsWith("/pilot-readiness")) return route.fulfill({json: pilotReadiness});
    return route.fulfill({json: []});
  });
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
  await expect(page.getByText("RtR Admin")).toBeVisible();
  await nav.getByRole("link", {name: "Quản trị"}).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("heading", {level: 1, name: "Quản trị"})).toBeVisible();
  await expect(nav.getByRole("link", {name: "Quản trị"}))
    .toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", {name: "Hỏi"}))
    .not.toHaveAttribute("aria-current", "page");
  await page.screenshot({path: "test-results/tip011-shell-desktop.png", fullPage: true});
});

test("desktop shell uses moderate compact density without shrinking body copy", async ({page}) => {
  await mockShell(page);
  await page.setViewportSize({width: 1280, height: 720});
  await page.goto("/ask");
  const density = await page.evaluate(() => {
    const measure = (selector: string) => {
      const node = document.querySelector(selector) as HTMLElement;
      const rect = node.getBoundingClientRect();
      return {width: rect.width, height: rect.height};
    };
    const main = getComputedStyle(document.querySelector(".pc-main") as HTMLElement);
    return {
      topbar: measure(".pc-topbar"),
      pageHeader: measure(".page-head"),
      heading: measure(".page-head h1"),
      bodySize: Number.parseFloat(getComputedStyle(document.querySelector(".pc-main") as HTMLElement).fontSize),
      mainPadding: Number.parseFloat(main.paddingLeft),
    };
  });
  expect(density.topbar.height).toBe(56);
  expect(density.pageHeader.height).toBeLessThanOrEqual(84);
  expect(density.heading.height).toBeLessThanOrEqual(38);
  expect(density.bodySize).toBeGreaterThanOrEqual(15);
  expect(density.mainPadding).toBeLessThanOrEqual(32);
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

test("the root opens Ask while legacy root file locators stay compatible", async ({page}) => {
  await mockShell(page, false);
  await page.goto("/");
  await expect(page).toHaveURL(/\/ask$/);
  await expect(page.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  await page.goto(`/?version=55555555-5555-4555-8555-555555555555&page=4`);
  await expect(page).toHaveURL(/\/files\?/);
  await expect(page).toHaveURL(/version=/);
});

test("staff navigation contains only usable workspace areas", async ({page}) => {
  await mockShell(page, true, ["staff"]);
  await page.goto("/ask");
  const nav = page.getByRole("navigation", {name: "Điều hướng chính"});
  await expect(nav.getByRole("link")).toHaveCount(3);
  await expect(nav.getByRole("link", {name: "Hỏi"})).toBeVisible();
  await expect(nav.getByRole("link", {name: "Tri thức"})).toHaveCount(0);
  await expect(nav.getByRole("link", {name: "Quản trị"})).toHaveCount(0);
});

test("global palette turns a phrase into an Ask prefill", async ({page}) => {
  await mockShell(page);
  await page.goto("/files");
  await page.getByRole("button", {name: "Hỏi hoặc tìm trong tri thức công ty"}).click();
  const dialog = page.getByRole("dialog", {name: "Hỏi hoặc tìm trong tri thức công ty"});
  await dialog.getByRole("textbox").fill("bảo hành robot");
  await dialog.getByRole("link", {name: /Hỏi Copilot:.*bảo hành robot/}).click();
  await expect(page).toHaveURL(/\/ask\?q=b%E1%BA%A3o%20h%C3%A0nh%20robot/);
  await expect(page.getByLabel("Câu hỏi")).toHaveValue("bảo hành robot");
});

test("anonymous shell keeps placeholders public and offers company sign-in", async ({page}) => {
  await mockShell(page, false);
  await page.goto("/ask");
  await expect(page.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  await expect(page.getByRole("link", {name: "Đăng nhập công ty"})).toBeVisible();
});

test("? opens the keyboard help dialog; Esc closes; inert inside text fields", async ({page}) => {
  await mockShell(page);
  await page.goto("/ask");
  await expect(page.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  await page.keyboard.press("?");
  const dialog = page.getByRole("dialog", {name: "Phím tắt bàn phím"});
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Tìm kiếm · bảng lệnh")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  // The topbar affordance opens it too.
  await page.getByRole("button", {name: "Phím tắt"}).click();
  await expect(page.getByRole("dialog", {name: "Phím tắt bàn phím"})).toBeVisible();
  await page.keyboard.press("Escape");
  // Typing ? inside the composer must NOT open the dialog.
  await page.locator(".ask-question textarea").click();
  await page.keyboard.type("?");
  await expect(page.getByRole("dialog", {name: "Phím tắt bàn phím"})).toBeHidden();
});

test("no-cookie visitor follows OS prefers-color-scheme; choosing a theme sets a cookie", async ({browser}) => {
  const dark = await browser.newContext({colorScheme: "dark"});
  const pd = await dark.newPage();
  await mockShell(pd);
  await pd.goto("/ask");
  await expect(pd.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  const bgDark = await pd.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await dark.close();

  const light = await browser.newContext({colorScheme: "light"});
  const pl = await light.newPage();
  await mockShell(pl);
  await pl.goto("/ask");
  await expect(pl.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  // No explicit cookie yet → no data-theme attribute; CSS resolves the OS scheme.
  expect(await pl.evaluate(() => document.documentElement.hasAttribute("data-theme"))).toBe(false);
  const bgLight = await pl.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bgDark).not.toBe(bgLight);
  // Choosing a theme writes the cookie + explicit attribute (overrides the OS).
  await pl.getByRole("button", {name: /Chuyển sang giao diện/}).click();
  await expect(pl.locator("html")).toHaveAttribute("data-theme", "dark");
  const cookie = (await light.cookies()).find(item => item.name === "rtr_theme");
  expect(cookie?.value).toBe("dark");
  await light.close();
});

test("collapsed sidebar has collision-free identity and mobile restores full labels", async ({page}) => {
  await mockShell(page, false);
  await page.setViewportSize({width: 1280, height: 720});
  await page.goto("/ask");
  const shell = page.locator(".pc-shell");
  const sidebar = page.locator(".pc-sidebar");
  const workspace = page.getByRole("button", {name: "Mở bảng lệnh không gian làm việc"});
  const collapse = page.getByRole("button", {name: "Thu gọn thanh bên"});
  await expect(page.locator(".pc-topbar .pc-brand")).toHaveCount(0);
  await expect(collapse).toHaveCSS("border-top-width", "0px");
  await expect(page.getByRole("button", {name: "Chuyển sang giao diện sáng"}))
    .toHaveCSS("border-top-width", "0px");
  await expect(workspace).toContainText("Copilot");
  await expect(workspace).not.toContainText("Real-time Robotics");
  await expect(workspace).not.toContainText("Không gian nội bộ");
  const searchBox = await page.locator(".pc-search").boundingBox();
  const pageHeaderBox = await page.locator(".page-head").boundingBox();
  expect(Math.abs((searchBox?.x ?? 0) - (pageHeaderBox?.x ?? 0)))
    .toBeLessThanOrEqual(1);
  const activeNav = sidebar.getByRole("link", {name: "Hỏi", exact: true});
  await expect(activeNav).toHaveCSS("border-top-width", "0px");
  await expect(activeNav).toHaveCSS("box-shadow", "none");
  expect(await activeNav.evaluate(element => getComputedStyle(element, "::before").width)).toBe("2px");
  await activeNav.hover();
  await expect.poll(() => activeNav.evaluate(
    element => getComputedStyle(element, "::before").width,
  )).toBe("3px");

  await collapse.click();
  await expect(shell).toHaveAttribute("data-collapsed", "true");
  const sideBox = await sidebar.boundingBox();
  const workspaceBox = await workspace.boundingBox();
  const collapseBox = await page.getByRole("button", {name: "Mở rộng thanh bên"}).boundingBox();
  expect(sideBox?.width).toBe(64);
  expect(Math.abs((workspaceBox?.x ?? 0) + (workspaceBox?.width ?? 0) / 2
    - ((collapseBox?.x ?? 0) + (collapseBox?.width ?? 0) / 2))).toBeLessThanOrEqual(1);
  expect((workspaceBox?.y ?? 0) + (workspaceBox?.height ?? 0))
    .toBeLessThanOrEqual(collapseBox?.y ?? 0);
  expect((workspaceBox?.x ?? 0) + (workspaceBox?.width ?? 0))
    .toBeLessThanOrEqual((sideBox?.x ?? 0) + (sideBox?.width ?? 0));
  await expect(page.locator(".pc-signin-label")).toBeHidden();
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )).toBeLessThanOrEqual(0);

  await page.setViewportSize({width: 390, height: 844});
  await page.getByRole("button", {name: "Điều hướng"}).click();
  await expect(sidebar).toHaveClass(/open/);
  await expect(page.locator(".pc-workspace-name")).toHaveText("Copilot");
  await expect(page.locator(".pc-signin-label")).toBeVisible();
  await expect(sidebar.getByRole("navigation", {name: "Điều hướng chính"})
    .getByRole("link", {name: "Hỏi", exact: true})).toBeVisible();
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )).toBeLessThanOrEqual(0);
});
