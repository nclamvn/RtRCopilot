/**
 * TIP-011 Builder D — AC-10 axe gate + AC-12 responsive/reduced-motion.
 *
 * Every primary page (/ask, /files, /documents, /knowledge-ops, /admin) is
 * scanned with axe-core at 360×800, 768×1024, 1440×900 and 1920×1080 in BOTH
 * locales with ZERO critical/serious violations, plus the key stateful
 * surfaces (grounded answer, honest-null, picker open, rail sheets and
 * drawers at mobile, approval footer, gated crossing). The same matrix
 * asserts zero horizontal overflow. Moderate/minor findings are recorded as
 * test annotations (reported, not gated).
 */

import AxeBuilder from "@axe-core/playwright";
import {expect, Page, test} from "@playwright/test";
import {
  groundedAnswer,
  honestNullAnswer,
  ids,
  mockAsk,
  mockAuth,
  mockDocuments,
  mockFiles,
  mockKnowledgeOps,
} from "./support/mocks";

const VIEWPORTS = [
  {name: "mobile", width: 360, height: 800},
  {name: "tablet", width: 768, height: 1024},
  {name: "desktop", width: 1440, height: 900},
  {name: "wide", width: 1920, height: 1080},
];
const LOCALES = ["vi", "en"] as const;

async function setLocale(page: Page, baseURL: string | undefined, locale: string) {
  await page.context().addCookies([{
    name: "rtr_locale", value: locale, url: baseURL ?? "http://127.0.0.1:3000",
  }]);
}

/** Zero critical/serious axe violations; moderate/minor become annotations. */
async function scan(page: Page, context: string) {
  const results = await new AxeBuilder({page}).analyze();
  const severe = results.violations.filter(
    violation => violation.impact === "critical" || violation.impact === "serious",
  );
  const lesser = results.violations.filter(
    violation => violation.impact !== "critical" && violation.impact !== "serious",
  );
  for (const violation of lesser) {
    test.info().annotations.push({
      type: "axe-moderate-minor",
      description:
        `${context}: ${violation.id} (${violation.impact}) ×${violation.nodes.length}`,
    });
  }
  expect(
    severe.map(violation => ({
      id: violation.id, impact: violation.impact,
      nodes: violation.nodes.map(node => node.target),
    })),
    `zero critical/serious axe violations — ${context}`,
  ).toEqual([]);
}

async function noOverflow(page: Page, context: string) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, `no horizontal overflow — ${context}`).toBeLessThanOrEqual(0);
}

async function sweep(page: Page, context: string) {
  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({width: viewport.width, height: viewport.height});
    const label = `${context} @${viewport.width}×${viewport.height}`;
    await noOverflow(page, label);
    await scan(page, label);
  }
}

/** AC-09 anchors: the H1, a nav label and one work-surface string must all
 *  render in the active locale (no mixed-language chrome; corpus/fixture
 *  data such as template display names stays server-provided and exempt). */
const LOCALE_ANCHORS = {
  vi: {nav: "Hỏi", h1: {ask: "Hỏi", files: "Tệp", documents: "Tài liệu",
    ops: "Vận hành tri thức", admin: "Quản trị"},
  surface: {files: "Tìm tệp", documents: "Mẫu đã duyệt",
    ops: "Bảng điều hành tri thức",
    admin: "Chưa có giao diện quản trị; các bề mặt API quản trị hiện có:"}},
  en: {nav: "Ask", h1: {ask: "Ask", files: "Files", documents: "Documents",
    ops: "Knowledge operations", admin: "Administration"},
  surface: {files: "Find files", documents: "Approved templates",
    ops: "Knowledge operations dashboard",
    admin: "No admin UI yet; existing admin API surfaces:"}},
} as const;

async function expectLocaleChrome(
  page: Page, locale: "vi" | "en", pageKey: keyof typeof LOCALE_ANCHORS.vi.h1,
) {
  const anchors = LOCALE_ANCHORS[locale];
  await expect(page.locator("html")).toHaveAttribute("lang", locale);
  await expect(page.getByRole("heading", {level: 1, name: anchors.h1[pageKey]}))
    .toBeVisible();
  await expect(page.getByRole("navigation")
    .filter({hasText: anchors.nav}).first()).toBeAttached();
  if (pageKey !== "ask") {
    await expect(page.getByText(
      anchors.surface[pageKey as keyof typeof anchors.surface]).first())
      .toBeAttached();
  }
}

for (const locale of LOCALES) {
  test(`axe matrix: /ask (${locale}) at all four viewports`, async ({page, baseURL}) => {
    await setLocale(page, baseURL, locale);
    await mockAsk(page);
    await page.goto("/ask");
    await expect(page.locator(".ask-question input")).toBeVisible();
    await expectLocaleChrome(page, locale, "ask");
    await sweep(page, `/ask ${locale}`);
  });

  test(`axe matrix: /files with open viewer (${locale}) at all four viewports`, async ({page, baseURL}) => {
    await setLocale(page, baseURL, locale);
    await mockAuth(page);
    await mockFiles(page);
    await page.goto(`/files?version=${ids.versionId}&page=4`);
    await expect(page.locator(".pdf-stage iframe")).toBeVisible();
    await expectLocaleChrome(page, locale, "files");
    await sweep(page, `/files ${locale}`);
  });

  test(`axe matrix: /documents (${locale}) at all four viewports`, async ({page, baseURL}) => {
    await setLocale(page, baseURL, locale);
    await mockDocuments(page);
    await page.goto("/documents");
    await expect(page.locator(".template-ledger li button").first()).toBeVisible();
    await expectLocaleChrome(page, locale, "documents");
    await sweep(page, `/documents ${locale}`);
  });

  test(`axe matrix: /knowledge-ops dashboard (${locale}) at all four viewports`, async ({page, baseURL}) => {
    await setLocale(page, baseURL, locale);
    await mockKnowledgeOps(page);
    await page.goto("/knowledge-ops");
    await expect(page.locator(".tile-grid .tile").first()).toBeVisible();
    await expectLocaleChrome(page, locale, "ops");
    await sweep(page, `/knowledge-ops ${locale}`);
  });

  test(`axe matrix: /admin (${locale}) at all four viewports`, async ({page, baseURL}) => {
    await setLocale(page, baseURL, locale);
    await mockAuth(page);
    await page.goto("/admin");
    await expect(page.locator(".placeholder-card li").first()).toBeVisible();
    await expectLocaleChrome(page, locale, "admin");
    await sweep(page, `/admin ${locale}`);
  });
}

test("axe stateful: grounded answer with rail entries (vi desktop + en desktop)", async ({page, baseURL}) => {
  for (const locale of LOCALES) {
    await setLocale(page, baseURL, locale);
    await mockAsk(page);
    await page.setViewportSize({width: 1440, height: 900});
    await page.goto("/ask");
    await page.locator(".ask-question input").fill("Chính sách bảo hành robot?");
    await page.locator(".ask-form button[type=submit]").click();
    await expect(page.locator(".answer-text")).toBeVisible();
    await expect(page.locator(".rail-entries article").first()).toBeVisible();
    await scan(page, `/ask grounded ${locale} @1440×900`);
    await page.unrouteAll({behavior: "ignoreErrors"});
  }
});

test("axe stateful: honest-null with recorded gap (vi desktop)", async ({page, baseURL}) => {
  await setLocale(page, baseURL, "vi");
  await mockAsk(page, honestNullAnswer);
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto("/ask");
  await page.locator(".ask-question input").fill("Điều chưa ai ghi lại?");
  await page.locator(".ask-form button[type=submit]").click();
  await expect(page.locator(".honest-null")).toBeVisible();
  await expect(page.getByText(ids.gapId, {exact: true})).toBeVisible();
  await scan(page, "/ask honest-null vi @1440×900");
});

test("axe stateful: ask file-scope picker open (vi desktop)", async ({page, baseURL}) => {
  await setLocale(page, baseURL, "vi");
  await mockAsk(page);
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto("/ask");
  await page.getByRole("button", {name: "Chọn tệp được cấp quyền"}).click();
  await expect(page.locator(".ask-file-list button").first()).toBeVisible();
  await scan(page, "/ask picker open vi @1440×900");
});

test("axe stateful: ask rail bottom sheet open at mobile (vi 360×800)", async ({page, baseURL}) => {
  await setLocale(page, baseURL, "vi");
  await mockAsk(page, groundedAnswer);
  await page.setViewportSize({width: 360, height: 800});
  await page.goto("/ask");
  await page.locator(".ask-question input").fill("Chính sách bảo hành robot?");
  await page.locator(".ask-form button[type=submit]").click();
  await expect(page.locator(".answer-text")).toBeVisible();
  await page.locator(".answer-text .citation-marker").first().click();
  await expect(page.locator("#evidence-rail")).toHaveClass(/open/);
  await noOverflow(page, "/ask rail sheet vi @360×800");
  await scan(page, "/ask rail sheet vi @360×800");
});

test("axe stateful: files rail sheet open at mobile (vi 360×800)", async ({page, baseURL}) => {
  await setLocale(page, baseURL, "vi");
  await mockAuth(page);
  await mockFiles(page);
  await page.setViewportSize({width: 360, height: 800});
  await page.goto(`/files?version=${ids.versionId}&page=4`);
  await expect(page.locator(".pdf-stage iframe")).toBeVisible();
  await page.locator(".rail-sheet-toggle").click();
  await expect(page.locator("#evidence-rail")).toHaveClass(/open/);
  await noOverflow(page, "/files rail sheet vi @360×800");
  await scan(page, "/files rail sheet vi @360×800");
});

test("axe stateful: documents bind + render + approval footer in the rail (vi desktop and 360 sheet)", async ({page, baseURL}) => {
  await setLocale(page, baseURL, "vi");
  await mockDocuments(page);
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto("/documents");
  await page.getByLabel("customer_name").fill("Nhà máy A");
  await page.getByRole("button", {name: "Kiểm tra dữ liệu"}).click();
  await expect(page.getByText("Dữ liệu hợp lệ và đã khóa nguồn.")).toBeVisible();
  await page.getByRole("button", {name: "Tạo bản xem"}).click();
  await expect(page.getByRole("region", {name: "Lưới bảng tính"})).toBeVisible();
  await expect(page.getByRole("button", {name: "Gửi duyệt"})).toBeVisible();
  await scan(page, "/documents rendered + approval rail vi @1440×900");
  await page.setViewportSize({width: 360, height: 800});
  await page.getByRole("button", {name: "SOT / duyệt"}).click();
  await expect(page.locator("#evidence-rail")).toHaveClass(/open/);
  await noOverflow(page, "/documents rail sheet vi @360×800");
  await scan(page, "/documents rail sheet vi @360×800");
});

test("axe stateful: knowledge-ops gap detail with subject picker open (vi desktop)", async ({page, baseURL}) => {
  await setLocale(page, baseURL, "vi");
  await mockKnowledgeOps(page);
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(`/knowledge-ops?view=gaps&gap=${ids.gapId}`);
  await expect(page.getByRole("heading", {name: "Chính sách bảo hành robot RtR là gì?"}))
    .toBeVisible();
  const subjectBox = page.getByRole("combobox", {name: "Người phụ trách"});
  await subjectBox.fill("RtR");
  await expect(page.getByRole("option", {name: /RtR Peer/})).toBeVisible();
  await scan(page, "/knowledge-ops picker open vi @1440×900");
});

test("axe stateful: knowledge-ops ledger drawer and rail sheet at mobile (vi 360×800)", async ({page, baseURL}) => {
  await setLocale(page, baseURL, "vi");
  await mockKnowledgeOps(page);
  await page.setViewportSize({width: 360, height: 800});
  await page.goto("/knowledge-ops");
  await page.getByRole("button", {name: "Hàng đợi", exact: true}).click();
  await expect(page.getByRole("navigation", {name: "Sổ hàng đợi"})).toHaveClass(/open/);
  await noOverflow(page, "/knowledge-ops ledger drawer vi @360×800");
  await scan(page, "/knowledge-ops ledger drawer vi @360×800");
  await page.keyboard.press("Escape");
  await page.getByRole("button", {name: "Bằng chứng", exact: true}).click();
  await expect(page.locator("#evidence-rail")).toHaveClass(/open/);
  await noOverflow(page, "/knowledge-ops rail sheet vi @360×800");
  await scan(page, "/knowledge-ops rail sheet vi @360×800");
});

test("axe stateful: graduation gated crossing (vi desktop)", async ({page, baseURL}) => {
  await setLocale(page, baseURL, "vi");
  await mockKnowledgeOps(page);
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(`/knowledge-ops?view=graduation&proposal=${ids.proposalId}`);
  await expect(page.locator(".gated-crossing")).toBeVisible();
  await scan(page, "/knowledge-ops gated crossing vi @1440×900");
});

test("axe stateful: shell mobile navigation drawer open (vi 360×800)", async ({page, baseURL}) => {
  await setLocale(page, baseURL, "vi");
  await mockAsk(page);
  await page.setViewportSize({width: 360, height: 800});
  await page.goto("/ask");
  await page.getByRole("button", {name: "Điều hướng", exact: true}).click();
  await expect(page.locator("#pc-sidebar")).toHaveClass(/open/);
  await noOverflow(page, "shell nav drawer vi @360×800");
  await scan(page, "shell nav drawer vi @360×800");
});

test("reduced motion: drawers, sheets and the gated crossing animate nothing (AC-12)", async ({page, baseURL}) => {
  await setLocale(page, baseURL, "vi");
  await page.emulateMedia({reducedMotion: "reduce"});
  await mockKnowledgeOps(page);
  await page.setViewportSize({width: 360, height: 800});
  await page.goto("/knowledge-ops");
  const durations = async (selector: string) => page.locator(selector).first()
    .evaluate(element => getComputedStyle(element).transitionDuration);
  // House kill-rule: `transition:none` under prefers-reduced-motion.
  expect(await durations(".ops-ledger")).toBe("0s");
  expect(await durations("#evidence-rail")).toBe("0s");
  expect(await durations("#shell-nav")).toBe("0s");
  // The gated crossing's moving marker is frozen; state still reads as text.
  await page.goto(`/knowledge-ops?view=graduation&proposal=${ids.proposalId}`);
  await expect(page.locator(".gated-crossing")).toBeVisible();
  expect(await durations(".crossing-marker")).toBe("0s");
  await expect(page.locator(".gated-crossing figcaption"))
    .toContainText("Đề xuất đang ở vùng RESEARCH");
  // No CSS animations run anywhere on the page under reduced motion.
  const animated = await page.evaluate(() =>
    Array.from(document.querySelectorAll("*")).filter(element => {
      const style = getComputedStyle(element);
      return style.animationName !== "none"
        && Number.parseFloat(style.animationDuration) > 0;
    }).length);
  expect(animated).toBe(0);
  // The Documents template drawer and the Files catalog drawer are equally
  // frozen (the kill rule is global; these are the remaining drawers).
  await mockDocuments(page);
  await mockFiles(page);
  await page.goto("/documents");
  await page.waitForSelector(".template-ledger");
  expect(await durations(".template-ledger")).toBe("0s");
  await page.goto("/files");
  await page.waitForSelector(".catalog");
  expect(await durations(".catalog")).toBe("0s");
});
