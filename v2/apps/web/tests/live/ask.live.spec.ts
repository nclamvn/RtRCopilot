import {expect, test, type Page} from "@playwright/test";

async function login(page: Page) {
  await page.goto("/api/auth/login");
  await page.goto("/ask");
  await expect(page.getByLabel("Câu hỏi")).toBeVisible();
}

async function ask(page: Page, question: string) {
  await page.getByLabel("Câu hỏi").fill(question);
  await page.getByRole("button", {name: "Gửi câu hỏi"}).click();
}

test("live colloquial company question renders a grounded cited answer", async ({page}) => {
  await login(page);
  await ask(page, "rtr là cty j vậy?");
  const answer = page.locator(".ask-answer");
  await expect(answer).toBeVisible();
  await expect(answer).toContainText("Real-time Robotics");
  await expect(answer.locator(".citation-marker").first()).toBeVisible();
  await expect(page).toHaveURL(/conversation=/);
});

test("live conversation resolves a pronoun follow-up", async ({page}) => {
  test.setTimeout(300_000);
  await login(page);
  await ask(page, "HERA là gì?");
  const profile = page.locator(".ask-answer");
  for (const term of [
    "HERA", "1-4-14", "56", "15 km", "HeraHub", "HeraSight LR",
    "Blue UAS", "24 tháng",
  ]) {
    await expect(profile).toContainText(term);
  }
  await expect(profile).toContainText(/12 (?:use case|trường hợp sử dụng)/i);
  await expect(profile).toContainText(/3(?:\/|,\s*)6(?:\/|\s+hoặc\s+)12 tháng/i);
  expect(await profile.locator(".citation-marker").count()).toBeGreaterThanOrEqual(10);
  const firstUrl = page.url();
  await ask(page, "thế nó bay được bao lâu?");
  await expect(page.locator(".ask-answer")).toContainText("56");
  expect(page.url()).toBe(firstUrl);
});

test("live exhaustive catalog keeps every governed member", async ({page}) => {
  await login(page);
  await ask(page, "RtR có các sản phẩm gì, liệt kê đầy đủ và cho biết tính năng chính?");
  const answer = page.locator(".ask-answer");
  await expect(answer).toBeVisible();
  for (const member of [
    "HERA", "VEGA", "HeraHub", "VegaHub", "HeraSight", "HeraSight LR",
    "VegaSight", "OmniSight", "DualSight", "SkyWatch 360", "LiDAR",
    "RAGAS", "AeroTunnel", "Dịch vụ", "Chưa xác định",
  ]) {
    await expect(answer).toContainText(member);
  }
  await expect(answer.locator(".citation-marker")).not.toHaveCount(0);
});

test("live ordinary broad catalog question returns useful best-effort content", async ({page}) => {
  test.setTimeout(180_000);
  await login(page);
  await ask(page, "bên mình có những sản phẩm gì vậy?");
  const answer = page.locator(".ask-answer");
  await expect(answer).toBeVisible();
  await expect(answer).toContainText("HERA");
  await expect(answer).toContainText("VEGA");
  await expect(answer.locator(".citation-marker").first()).toBeVisible();
  await expect(page.getByRole("heading", {name: "Chưa có bằng chứng"}))
    .toHaveCount(0);
});

test("live unknown entity is honest-null and exposes no evidence", async ({page}) => {
  await login(page);
  await ask(page, "ORION là sản phẩm gì của công ty?");
  await expect(page.getByRole("heading", {name: "Chưa có bằng chứng"})).toBeVisible();
  await expect(page.locator(".honest-null")).toContainText(
    "Không tìm thấy bằng chứng được phép và đủ tin cậy",
  );
  await expect(page.locator(".ask-answer")).toHaveCount(0);
});
