import {expect, test} from "@playwright/test";

for (const viewport of [
  {name: "mobile", width: 360, height: 800},
  {name: "desktop", width: 1440, height: 900},
]) {
  test(`${viewport.name} foundation smoke`, async ({page}) => {
    await page.setViewportSize(viewport);
    await page.goto("/");

    await expect(page.getByRole("heading", {
      name: "V2 foundation · chưa có dữ liệu",
    })).toBeVisible();
    await expect(page.locator(".status")).toContainText("ready");
    await expect(page.locator(".status")).toContainText("postgres");
    await expect(page.locator(".status")).toContainText("redis");
    await expect(page.locator(".status")).toContainText("object_storage");

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    const readinessLink = page.getByRole("link", {name: /Kiểm tra readiness/});
    await expect(readinessLink).toBeFocused();
    const outline = await readinessLink.evaluate(element => {
      const styles = getComputedStyle(element);
      return {style: styles.outlineStyle, width: Number.parseFloat(styles.outlineWidth)};
    });
    expect(outline.style).not.toBe("none");
    expect(outline.width).toBeGreaterThanOrEqual(3);
  });
}

test("corporate fake login, policy deny, and logout", async ({page, context}) => {
  await context.clearCookies();
  await page.goto("/");
  await expect(page.getByRole("link", {name: "Đăng nhập công ty"})).toBeVisible();

  await page.getByRole("link", {name: "Đăng nhập công ty"}).click();
  await expect(page.getByText("staff@rtrobotics.com")).toBeVisible();
  await expect(page.getByRole("button", {name: "Đăng xuất"})).toBeVisible();

  const cookies = await context.cookies();
  const session = cookies.find(cookie => cookie.name === "rtr_session");
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Lax");
  expect(session?.path).toBe("/");
  const browserStorage = await page.evaluate(() => ({
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
  }));
  expect(browserStorage).toEqual({local: [], session: []});

  const denied = await page.request.get(
    "/api/auth/dev/protected?action=view&classification=classified",
  );
  expect(denied.status()).toBe(403);
  expect((await denied.json()).error.code).toBe("classification_denied");

  await page.getByRole("button", {name: "Đăng xuất"}).click();
  await expect(page.getByRole("link", {name: "Đăng nhập công ty"})).toBeVisible();
  expect((await context.cookies()).some(cookie => cookie.name === "rtr_session")).toBe(false);
});
