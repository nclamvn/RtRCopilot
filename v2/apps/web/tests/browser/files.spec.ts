import {expect, Page, test} from "@playwright/test";

const versionId = "22222222-2222-4222-8222-222222222222";
const documentId = "33333333-3333-4333-8333-333333333333";
const renditionId = "11111111-1111-4111-8111-111111111111";
const dataRenditionId = "55555555-5555-4555-8555-555555555555";
const sha = "a".repeat(64);
const safeImage = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600">
  <rect width="960" height="600" fill="#11181c"/>
  <path d="M80 300h800M480 70v460" stroke="#76a8b3" stroke-width="2"/>
  <circle cx="480" cy="300" r="150" fill="none" stroke="#e56b46" stroke-width="8"/>
  <text x="480" y="315" text-anchor="middle" fill="#e8e6e3"
    font-family="monospace" font-size="34">RTR SAFE PREVIEW</text>
</svg>`;

function renditions(kind: string) {
  const item = (renditionKind: string, mime: string) => {
    const id = mime === "application/json" ? dataRenditionId : renditionId;
    return {
    rendition_id: id, kind: renditionKind, mime_type: mime,
    byte_size: 120, sha256: sha, quality_state: "complete",
    content_url: `/api/v1/files/renditions/${id}/content`,
  };};
  if (kind === "image") return [item("safe_image_preview", "image/png"), item("ocr_json", "application/json")];
  if (kind === "pdf") return [item("preview_pdf", "application/pdf"), item("page_text_json", "application/json")];
  if (kind === "docx" || kind === "pptx") {
    return [item("preview_pdf", "application/pdf"), item("structured_text_json", "application/json")];
  }
  if (kind === "xlsx") return [item("sheet_preview_json", "application/json")];
  return [item(kind === "video" ? "browser_video" : "browser_audio", kind === "video" ? "video/mp4" : "audio/mp4"),
    item("transcript_json", "application/json")];
}

function manifestFor(kind: string) {
  return {
    schema_version: 1, version_id: versionId, source_sha256: sha,
    detected_mime: "application/octet-stream", viewer_kind: kind, state: "ready",
    capabilities: {
      preview: true, text: true, search_within_file: true,
      deep_link: true, download_original: false,
    },
    renditions: renditions(kind), locator_schema: "rtr.locator.v1",
    quality: {}, warnings: kind === "docx" || kind === "pptx"
      ? ["semantic_preview_layout_may_differ"] : [],
  };
}

async function mockWorkspace(page: Page, kind: string) {
  await page.route("**/api/status", route => route.fulfill({json: {ok: true, status: "ready"}}));
  await page.route("**/api/auth/me", route => route.fulfill({json: {
    user_id: "44444444-4444-4444-8444-444444444444",
    email: "staff@rtrobotics.com", display_name: "RtR Staff", roles: ["staff"],
  }}));
  await page.route("**/api/files**", async route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/files") {
      return route.fulfill({json: {items: [{
        document_id: documentId, version_id: versionId, logical_name: `fixture.${kind}`,
        display_filename: `fixture.${kind}`, detected_mime: "application/octet-stream",
        viewer_kind: kind, viewer_state: "ready", byte_size: 120,
        classification: "internal", owner_display_name: "RtR Staff",
        version_created_at: "2026-07-31T00:00:00Z", quality: {}, warnings: [],
        can_download: false,
      }], next_cursor: null}});
    }
    if (url.pathname.endsWith("/upload-targets")) return route.fulfill({json: {items: []}});
    if (url.pathname.endsWith("/viewer-manifest")) {
      return route.fulfill({json: manifestFor(kind)});
    }
    if (url.pathname.includes("/renditions/")) {
      const json = kind === "xlsx"
        ? {sheets: [{
            sheet: "Data",
            rows: [{row: 1, cells: [{cell: "A1", value: "Rotor", formula: "=UPPER(\"rotor\")"}]}],
            merged_ranges: ["A1:B1"],
          }, {
            sheet: "Archive",
            rows: [{row: 8, cells: [{cell: "C8", value: "Secondary rotor", formula: null}]}],
            merged_ranges: [],
          }]}
        : kind === "video" || kind === "audio"
          ? {segments: [{start_ms: 500, end_ms: 1000, text: "Rotor status"}]}
          : kind === "image"
            ? {regions: [{page: 1, region: "p1-r1", text: "Rotor status"}]}
            : {pages: [{page: 1, text: "Rotor status"}], paragraphs: [{paragraph: 0, text: "Rotor status"}]};
      if (kind === "image" && !url.pathname.includes(dataRenditionId)) {
        return route.fulfill({body: safeImage, contentType: "image/svg+xml"});
      }
      return route.fulfill({json});
    }
    return route.fulfill({status: 404, json: {error: {code: "not_found"}}});
  });
}

for (const kind of ["image", "pdf", "docx", "xlsx", "pptx", "video", "audio"]) {
  test(`${kind} viewer uses an authorized safe rendition`, async ({page}) => {
    await mockWorkspace(page, kind);
    await page.goto("/");
    await page.getByRole("button", {name: `fixture.${kind}`}).click();
    await expect(page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"}))
      .toContainText(kind);
    if (kind === "image") await expect(page.getByAltText("Bản ảnh an toàn đã loại metadata")).toBeVisible();
    if (["pdf", "docx", "pptx"].includes(kind)) {
      await expect(page.getByTitle("Bản xem PDF an toàn")).toBeVisible();
    }
    if (kind === "xlsx") {
      await expect(page.getByRole("region", {name: "Lưới bảng tính"})).toBeVisible();
      await expect(page.getByText("Ô gộp: A1:B1")).toBeVisible();
      await expect(page.getByTitle("Công thức")).toContainText("UPPER");
      await page.getByRole("textbox", {name: "Tìm trong tệp"}).fill("Secondary");
      await page.getByRole("button", {name: /Secondary rotor/}).click();
      await expect(page.getByRole("tab", {name: "Archive"})).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("region", {name: "Lưới bảng tính"})
        .getByRole("button", {name: "Secondary rotor", exact: true})).toBeVisible();
    }
    if (kind === "video") await expect(page.locator("video")).toBeVisible();
    if (kind === "audio") await expect(page.locator("audio")).toBeVisible();
  });
}

for (const viewport of [
  {name: "mobile", width: 360, height: 800},
  {name: "tablet", width: 768, height: 1024},
  {name: "desktop", width: 1440, height: 900},
]) {
  test(`${viewport.name} workspace is keyboard-safe and has no page overflow`, async ({page}) => {
    await mockWorkspace(page, "image");
    await page.setViewportSize(viewport);
    await page.goto("/");
    if (viewport.width <= 720) {
      await page.getByRole("button", {name: "Danh mục", exact: true}).click();
    }
    await page.getByRole("button", {name: "fixture.image"}).click();
    await expect(page.locator(".catalog")).not.toHaveClass(/open/);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await page.keyboard.press("Tab");
    const focusedOutline = await page.evaluate(() => {
      const style = getComputedStyle(document.activeElement as Element);
      return Number.parseFloat(style.outlineWidth);
    });
    expect(focusedOutline).toBeGreaterThanOrEqual(3);
    if (viewport.name === "mobile" || viewport.name === "desktop") {
      await page.waitForTimeout(220);
      await page.screenshot({
        path: `test-results/tip008-${viewport.name}.png`,
        fullPage: true,
      });
    }
  });
}

test("anonymous user does not issue a file request", async ({page}) => {
  let fileRequests = 0;
  await page.route("**/api/status", route => route.fulfill({json: {ok: true, status: "ready"}}));
  await page.route("**/api/auth/me", route => route.fulfill({status: 401, json: {}}));
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/files")) fileRequests += 1;
  });
  await page.goto("/");
  await expect(page.getByRole("link", {name: "Đăng nhập công ty"})).toBeVisible();
  expect(fileRequests).toBe(0);
});

test("retryable upload exposes progress and opens the accepted version without reload", async ({page}) => {
  await mockWorkspace(page, "pdf");
  const targetId = "66666666-6666-4666-8666-666666666666";
  const uploadId = "77777777-7777-4777-8777-777777777777";
  let retried = false;
  await page.route("**/api/files/upload-targets", route => route.fulfill({json: {items: [{
    target_id: targetId, label: "Tài liệu kỹ thuật", classification: "internal",
  }]}}));
  await page.route("**/api/files/uploads**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/files/uploads" && request.method() === "POST") {
      return route.fulfill({status: 202, json: {
        upload_id: uploadId, job_id: "job-1", state: "uploading",
        progress: 0, retryable: false,
        status_url: `/api/v1/files/uploads/${uploadId}`,
      }});
    }
    if (path.endsWith("/retry") && request.method() === "POST") {
      retried = true;
      return route.fulfill({status: 202, json: {ok: true}});
    }
    return route.fulfill({json: retried ? {
      upload_id: uploadId, job_id: "job-2", state: "accepted",
      progress: 100, retryable: false, version_id: versionId,
    } : {
      upload_id: uploadId, job_id: "job-1", state: "failed",
      progress: 64, retryable: true, error_code: "worker_interrupted",
      failed_stage: "extract",
    }});
  });
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: "fixture.pdf", mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.7 deterministic fixture"),
  });
  await expect(page.getByText("failed · 64%")).toBeVisible();
  await page.getByRole("button", {name: "Thử lại"}).click();
  await expect(page.getByText("accepted · 100%")).toBeVisible();
  await expect(page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"})).toContainText("pdf");
});

test("revoked JSON rendition clears selected content and evidence metadata", async ({page}) => {
  await mockWorkspace(page, "xlsx");
  await page.route(
    `**/api/files/renditions/${dataRenditionId}/content`,
    route => route.fulfill({status: 404, json: {error: {code: "not_found"}}}),
  );
  await page.goto("/");
  await page.getByRole("button", {name: "fixture.xlsx"}).click();
  await expect(page.getByRole("heading", {name: "Chọn một tệp để bắt đầu"})).toBeVisible();
  await expect(page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"}))
    .toContainText("Chưa có bằng chứng để hiển thị.");
});

test("focus revalidation clears an image after access is revoked", async ({page}) => {
  await mockWorkspace(page, "image");
  let revoked = false;
  await page.route(`**/api/files/versions/${versionId}/viewer-manifest`, route => (
    revoked
      ? route.fulfill({status: 404, json: {error: {code: "not_found"}}})
      : route.fulfill({json: manifestFor("image")})
  ));
  await page.goto("/");
  await page.getByRole("button", {name: "fixture.image"}).click();
  await expect(page.getByAltText("Bản ảnh an toàn đã loại metadata")).toBeVisible();
  revoked = true;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("heading", {name: "Chọn một tệp để bắt đầu"})).toBeVisible();
});

test("catalog session revocation clears the entire workspace", async ({page}) => {
  await mockWorkspace(page, "pdf");
  let revoked = false;
  await page.route("**/api/files?**", route => (
    revoked
      ? route.fulfill({status: 401, json: {error: {code: "authentication_required"}}})
      : route.fulfill({json: {items: [{
          document_id: documentId, version_id: versionId, logical_name: "fixture.pdf",
          display_filename: "fixture.pdf", detected_mime: "application/pdf",
          viewer_kind: "pdf", viewer_state: "ready", byte_size: 120,
          classification: "internal", owner_display_name: "RtR Staff",
          version_created_at: "2026-07-31T00:00:00Z", quality: {}, warnings: [],
          can_download: false,
        }], next_cursor: null}})
  ));
  await page.goto("/");
  await page.getByRole("button", {name: "fixture.pdf"}).click();
  await expect(page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"})).toContainText("pdf");
  revoked = true;
  await page.getByRole("textbox", {name: "Tìm tệp"}).fill("revoked");
  // Shell adoption (TIP-011): the page drops to its gate lede — the shell
  // topbar keeps its own session state, so the page-level gate is the proof.
  await expect(page.getByText(/Đăng nhập bằng email công ty/)).toBeVisible();
  await expect(page.getByRole("button", {name: "fixture.pdf"})).toHaveCount(0);
});
