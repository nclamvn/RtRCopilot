import AxeBuilder from "@axe-core/playwright";
import {expect, test} from "@playwright/test";
import {mockIntelligence} from "./support/mocks";

test("briefing keeps SOT and Research visibly separate and opens evidence", async ({page}) => {
  await mockIntelligence(page);
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto("/intelligence");
  await expect(page.getByRole("heading", {level: 1, name: "Tín hiệu"})).toBeVisible();
  const feed = page.getByRole("region", {name: "Tín hiệu"});
  await expect(feed.getByText("Nguồn sự thật")).toHaveCount(2);
  await expect(feed.getByText("Nghiên cứu · chưa là SOT")).toHaveCount(1);
  await expect(page.getByText(/Bản ghi này cần được rà soát độ mới/)).toBeVisible();
  await expect(page.getByText("server copy")).toHaveCount(0);

  await page.getByRole("button", {name: /Precision agriculture market signal/}).click();
  const rail = page.getByRole("complementary", {name: "Nguồn đối chiếu"});
  await expect(rail.getByRole("heading", {name: "Precision agriculture market signal"}))
    .toBeVisible();
  await expect(rail.getByText("corroborated")).toBeVisible();
  await expect(rail.getByRole("link", {name: /Hỏi tiếp/}))
    .toHaveAttribute("href", /\/ask\?q=/);
});

test("follow-up handoff prefills Ask without synthesizing inside the briefing", async ({page}) => {
  await mockIntelligence(page);
  await page.goto("/intelligence");
  const article = page.getByRole("article").filter({hasText: "HERA product roadmap"});
  await article.getByRole("link", {name: /Hỏi tiếp/}).click();
  await expect(page).toHaveURL(/\/ask\?q=/);
  await expect(page.getByLabel("Câu hỏi"))
    .toHaveValue("Giải thích tác động của roadmap HERA.");
});

for (const viewport of [
  {name: "mobile", width: 360, height: 800},
  {name: "desktop", width: 1440, height: 900},
]) {
  test(`briefing is accessible and balanced at ${viewport.name}`, async ({page}) => {
    await mockIntelligence(page);
    await page.setViewportSize({width: viewport.width, height: viewport.height});
    await page.goto("/intelligence");
    await expect(page.getByRole("heading", {level: 1, name: "Tín hiệu"})).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    const results = await new AxeBuilder({page}).analyze();
    const severe = results.violations.filter(
      violation => violation.impact === "critical" || violation.impact === "serious",
    );
    expect(severe.map(item => item.id)).toEqual([]);
    if (viewport.name === "mobile") {
      const targets = await page.locator(
        ".intelligence-refresh, .intelligence-item-select, .intelligence-item-actions a",
      ).evaluateAll(nodes => nodes.map(node => ({
        width: node.getBoundingClientRect().width,
        height: node.getBoundingClientRect().height,
      })));
      expect(targets.every(target => target.height >= 44 || target.width >= 44)).toBe(true);
    }
  });
}
