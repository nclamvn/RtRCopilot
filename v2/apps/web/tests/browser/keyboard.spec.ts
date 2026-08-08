/**
 * TIP-011 Builder D — AC-11 keyboard-only critical flows.
 *
 * Complements the existing keyboard proofs (ask → citation → rail → viewer
 * in ask.spec.ts; skip link + F6 cycling in shell.spec.ts/ask.spec.ts) with:
 * file open → deep locator, documents template → bind → render → approve
 * (approval form lives in the Evidence Rail — focus order verified),
 * ops triage → assign → answer through the TIP-011 pickers, language
 * switch, and focus landing on the work surface after a route change.
 * Every flow uses ONLY the keyboard and asserts the quiet focus indicator.
 */

import {expect, Locator, Page, test} from "@playwright/test";
import {ids, mockAuth, mockDocuments, mockFiles, mockKnowledgeOps} from "./support/mocks";

/** Press Tab (or Shift+Tab) until the locator's element holds focus. */
async function tabUntilFocused(
  page: Page, locator: Locator, options: {backwards?: boolean; max?: number} = {},
) {
  const key = options.backwards ? "Shift+Tab" : "Tab";
  const max = options.max ?? 60;
  for (let step = 0; step < max; step += 1) {
    await page.keyboard.press(key);
    const focused = await locator
      .evaluate(element => element === document.activeElement)
      .catch(() => false);
    if (focused) return;
  }
  throw new Error(`tabUntilFocused: target never received focus (${key} ×${max})`);
}

/** Focus stays visible without bringing back a surrounding focus frame. */
async function expectVisibleFocus(page: Page) {
  const focus = await page.evaluate(() => {
    const style = getComputedStyle(document.activeElement as Element);
    return {
      outline: Number.parseFloat(style.outlineWidth),
      shadow: style.boxShadow,
      decoration: style.textDecorationLine,
    };
  });
  expect(focus.outline).toBe(0);
  expect(focus.shadow !== "none" || focus.decoration.includes("underline")).toBe(true);
}

test("keyboard-only: file open → deep locator (pager moves the rtr.locator.v1 position)", async ({page}) => {
  await mockAuth(page);
  await mockFiles(page);
  await page.goto("/files");
  await expect(page.getByRole("heading", {level: 1, name: "Tệp"})).toBeVisible();
  // Skip link first, then into the catalog to the file row.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", {name: "Bỏ qua tới nội dung chính"})).toBeFocused();
  await page.keyboard.press("Enter");
  const fileButton = page.getByRole("button", {name: /company-spec\.pdf/});
  await tabUntilFocused(page, fileButton);
  await expectVisibleFocus(page);
  await page.keyboard.press("Enter");
  await expect(page.getByTitle("Bản xem PDF an toàn")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`version=${ids.versionId}`));
  // Deep locator by keyboard: the pager advances the locator to page 2.
  const nextPage = page.getByRole("button", {name: "Trang sau"});
  await tabUntilFocused(page, nextPage);
  await expectVisibleFocus(page);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/page=2/);
  await expect(page.locator(".pager output")).toContainText("2 / 4");
});

test("keyboard-only: documents template → bind → render → approve; approval form in the rail keeps a sane focus order", async ({page}) => {
  await mockDocuments(page);
  await page.goto("/documents");
  await expect(page.getByRole("heading", {level: 1, name: "Tài liệu"})).toBeVisible();
  // Template selection from the registry, keyboard only.
  const template = page.getByRole("button", {name: /Báo cáo vận hành/});
  await tabUntilFocused(page, template);
  await expectVisibleFocus(page);
  await page.keyboard.press("Enter");
  // Fill the user binding and bind.
  const customer = page.getByLabel(/customer_name/);
  await tabUntilFocused(page, customer);
  await page.keyboard.type("Nhà máy A");
  const bind = page.getByRole("button", {name: "Kiểm tra dữ liệu"});
  await tabUntilFocused(page, bind);
  await page.keyboard.press("Enter");
  await expect(page.getByText("Dữ liệu hợp lệ và đã khóa nguồn.")).toBeVisible();
  // Render.
  const render = page.getByRole("button", {name: "Tạo bản xem"});
  await tabUntilFocused(page, render);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", {name: "Lưới bảng tính"})).toBeVisible();
  // The approval form lives INSIDE the shared Evidence Rail: forward tab
  // order flows desk → rail; the reason field is immediately followed by
  // the submit action (focus-order proof for the rail form).
  const reasonInput = page.getByLabel("Lý do", {exact: true});
  await tabUntilFocused(page, reasonInput);
  await page.keyboard.type("Đủ điều kiện gửi duyệt");
  await page.keyboard.press("Tab");
  const submit = page.getByRole("button", {name: "Gửi duyệt"});
  await expect(submit).toBeFocused();
  await expectVisibleFocus(page);
  await page.keyboard.press("Enter");
  // in_review → approve, still keyboard only.
  const approve = page.getByRole("button", {name: "Duyệt", exact: true});
  await expect(approve).toBeVisible();
  await tabUntilFocused(page, approve);
  await expectVisibleFocus(page);
  await page.keyboard.press("Enter");
  await expect(page.locator(".state-chip")).toHaveText("approved");
  await expect(page.getByRole("button", {name: "Phát hành"})).toBeVisible();
});

test("keyboard-only: ops triage → assign (subject picker) → answer (record picker)", async ({page}) => {
  await mockKnowledgeOps(page);
  await page.goto(`/knowledge-ops?view=gaps&gap=${ids.gapId}`);
  await expect(page.getByRole("heading", {name: "Chính sách bảo hành robot RtR là gì?"}))
    .toBeVisible();
  // Reason, then triage.
  const reason = page.getByLabel("Lý do thao tác");
  await tabUntilFocused(page, reason);
  await expectVisibleFocus(page);
  await page.keyboard.type("Câu hỏi lặp lại nhiều lần");
  const triage = page.getByRole("button", {name: "Nhận xử lý"});
  await tabUntilFocused(page, triage);
  await page.keyboard.press("Enter");
  await expect(page.locator(".transition-history")).toContainText("open → triaged");
  // Assign through the WAI-ARIA subject combobox: type → listbox option →
  // Enter selects (the active option carries aria-activedescendant).
  const subjectBox = page.getByRole("combobox", {name: "Người phụ trách"});
  await tabUntilFocused(page, subjectBox, {backwards: true});
  await expectVisibleFocus(page);
  await page.keyboard.type("RtR");
  await expect(page.getByRole("option", {name: /RtR Peer/})).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Đã chọn:")).toBeVisible();
  const assign = page.getByRole("button", {name: "Giao cho", exact: true});
  await tabUntilFocused(page, assign);
  await expect(assign).toBeEnabled();
  await page.keyboard.press("Enter");
  await expect(page.locator(".transition-history")).toContainText("triaged → assigned");
  // Answer through the record picker (SOT-labeled active records).
  const recordBox = page.getByRole("combobox", {name: "Bản ghi SOT trả lời"});
  await tabUntilFocused(page, recordBox, {backwards: true});
  await page.keyboard.type("warranty");
  await expect(page.getByRole("option", {name: /company\.warranty/})).toBeVisible();
  await page.keyboard.press("Enter");
  const answer = page.getByRole("button", {name: "Trả lời bằng bản ghi đã phát hành"});
  await tabUntilFocused(page, answer);
  await expect(answer).toBeEnabled();
  await page.keyboard.press("Enter");
  await expect(page.locator(".transition-history")).toContainText("assigned → answered");
});

test("keyboard-only: language switch flips the whole chrome and stays keyboard-operable", async ({page}) => {
  await mockKnowledgeOps(page);
  await page.goto("/knowledge-ops");
  await expect(page.getByRole("heading", {level: 1, name: "Vận hành tri thức"}))
    .toBeVisible();
  const enButton = page.getByRole("button", {name: "EN", exact: true});
  await tabUntilFocused(page, enButton);
  await expectVisibleFocus(page);
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", {level: 1, name: "Knowledge operations"}))
    .toBeVisible();
  // And back, keyboard only.
  const viButton = page.getByRole("button", {name: "VI", exact: true});
  await tabUntilFocused(page, viButton, {backwards: true, max: 5});
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("lang", "vi");
  await expect(page.getByRole("heading", {level: 1, name: "Vận hành tri thức"}))
    .toBeVisible();
});

test("route change moves focus to the work surface (focus management, AC-11)", async ({page}) => {
  await mockAuth(page);
  await mockFiles(page);
  await page.goto("/ask");
  await expect(page.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  // Reach the nav by keyboard (F6 is the shell's region shortcut).
  await page.keyboard.press("F6");
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("shell-nav");
  const filesLink = page.getByRole("navigation", {name: "Điều hướng chính"})
    .getByRole("link", {name: "Tệp"});
  await tabUntilFocused(page, filesLink, {max: 10});
  await expectVisibleFocus(page);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/files$/);
  await expect(page.getByRole("heading", {level: 1, name: "Tệp"})).toBeVisible();
  // AC-11: after the route change, focus lands on the main landmark that
  // holds the page's single H1 — not on a stale control.
  await expect.poll(() => page.evaluate(() => document.activeElement?.id)).toBe("main");
});
