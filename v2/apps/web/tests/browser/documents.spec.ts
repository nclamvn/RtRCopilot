import {expect, Page, test} from "@playwright/test";

const templateId = "11111111-1111-4111-8111-111111111111";
const templateVersionId = "22222222-2222-4222-8222-222222222222";
const renderJobId = "33333333-3333-4333-8333-333333333333";
const generatedId = "44444444-4444-4444-8444-444444444444";
const fileVersionId = "55555555-5555-4555-8555-555555555555";
const renditionId = "66666666-6666-4666-8666-666666666666";
const sha = "a".repeat(64);

async function mockDocuments(page: Page) {
  await page.route("**/api/auth/me", route => route.fulfill({json: {
    user_id: "77777777-7777-4777-8777-777777777777",
    email: "staff@rtrobotics.com", display_name: "RtR Staff", roles: ["staff"],
  }}));
  await page.route("**/api/document-os/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/document-os/templates") return route.fulfill({json: {items: [{
      template_id: templateId, version_id: templateVersionId,
      stable_key: "official.report", display_name: "Báo cáo vận hành",
      category: "Operations", classification: "internal", document_class: "official",
      format: "xlsx", version_ordinal: 3, status: "approved",
      owner_display_name: "Curator",
    }], next_cursor: null}});
    if (path.endsWith(`/templates/${templateId}/versions/${templateVersionId}`)) {
      return route.fulfill({json: {
        template_id: templateId, version_id: templateVersionId, status: "approved",
        source_sha256: sha, renderer_kind: "xlsx_declarative", renderer_version: "rtr-doc-os-1",
        schema: {schema_version: 1, bindings: [
          {field_path: "customer_name", field_type: "string", source: "user", required: true},
          {field_path: "company_name", field_type: "string", source: "locked_fact", required: true,
            record_key: "company.name"},
        ]},
      }});
    }
    if (path.endsWith("/bind")) return route.fulfill({json: {
      valid: true, missing: [], blocked: [], sot_revision: 9,
      fields: [
        {field_path: "customer_name", source: "user", value: "Nhà máy A"},
        {field_path: "company_name", source: "locked_fact", value: "Real-time Robotics",
          record_key: "company.name", record_checksum: "b".repeat(64),
          evidence_checksum: "c".repeat(64), provenance_level: "verified_primary",
          freshness_state: "current"},
      ],
    }});
    if (path.endsWith("/render") && route.request().method() === "POST") {
      return route.fulfill({json: {render_job_id: renderJobId, state: "pending", progress: 0}});
    }
    if (path.endsWith(`/render-jobs/${renderJobId}`)) return route.fulfill({json: {
      render_job_id: renderJobId, state: "completed", progress: 100,
      generated_file_id: generatedId, version_id: fileVersionId, checksum: sha,
    }});
    if (path.endsWith(`/generated/${generatedId}`)) return route.fulfill({json: {
      generated_file_id: generatedId, render_job_id: renderJobId,
      template_version_id: templateVersionId, version_id: fileVersionId,
      output_format: "xlsx", checksum: sha, lifecycle: "draft",
      render_manifest: {}, created_at: "2026-07-31T00:00:00Z", approvals: [],
    }});
    if (path.endsWith("/documents/history")) return route.fulfill({json: {
      template_id: templateId, items: [{
        generated_file_id: generatedId, template_version_id: templateVersionId,
        version_id: fileVersionId, lifecycle: "draft", checksum: sha,
        created_at: "2026-07-31T00:00:00Z",
        parameters: {customer_name: "Nhà máy A"},
        locked_snapshots: {company_name: {record_checksum: "b".repeat(64)}},
        comparison: {
          previous_generated_file_id: "88888888-8888-4888-8888-888888888888",
          changed_parameters: ["customer_name"], changed_locked_facts: ["company_name"],
          template_changed: false, checksum_changed: true, lifecycle_changed: false,
        },
      }],
    }});
    return route.fulfill({status: 404, json: {error: {code: "not_found"}}});
  });
  await page.route("**/api/files/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/viewer-manifest")) return route.fulfill({json: {
      schema_version: 1, version_id: fileVersionId, source_sha256: sha,
      detected_mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      viewer_kind: "xlsx", state: "ready",
      capabilities: {preview: true, text: true, search_within_file: true,
        deep_link: true, download_original: false},
      renditions: [{rendition_id: renditionId, kind: "sheet_preview_json",
        mime_type: "application/json", byte_size: 120, sha256: sha,
        quality_state: "complete",
        content_url: `/api/v1/files/renditions/${renditionId}/content`}],
      locator_schema: "rtr.locator.v1", quality: {}, warnings: [],
    }});
    if (path.includes(renditionId)) return route.fulfill({json: {sheets: [{
      sheet: "Report", rows: [{row: 1, cells: [{cell: "A1", value: "Real-time Robotics"}]}],
      merged_ranges: [],
    }]}});
    return route.fulfill({status: 404, json: {error: {code: "not_found"}}});
  });
}

test("authorized user binds SOT, renders and sees official draft truth", async ({page}) => {
  await mockDocuments(page);
  await page.goto("/documents");
  await page.getByLabel("customer_name").fill("Nhà máy A");
  await page.getByRole("button", {name: "Kiểm tra dữ liệu"}).click();
  await expect(page.getByText("Dữ liệu hợp lệ và đã khóa nguồn.")).toBeVisible();
  await expect(page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"}))
    .toContainText("verified_primary");
  await page.getByRole("button", {name: "Tạo bản xem"}).click();
  await expect(page.getByRole("region", {name: "Lưới bảng tính"})).toBeVisible();
  await expect(page.getByLabel("Trạng thái bản nháp")).toContainText("CHƯA PHÁT HÀNH");
  await expect(page.getByText("Tham số đổi: customer_name")).toBeVisible();
  await expect(page.getByText("SOT đổi: company_name")).toBeVisible();
  await page.screenshot({path: "test-results/tip009-documents-desktop.png", fullPage: true});
});

test("mobile Documents workspace has no page overflow and opens both drawers", async ({page}) => {
  await mockDocuments(page);
  await page.setViewportSize({width: 360, height: 800});
  await page.goto("/documents");
  await page.getByRole("button", {name: "Mẫu", exact: true}).click();
  await expect(page.getByRole("complementary", {name: "Template registry"})).toHaveClass(/open/);
  await page.waitForTimeout(250);
  await page.screenshot({path: "test-results/tip009-documents-mobile-ledger.png", fullPage: true});
  await page.getByRole("button", {name: /Báo cáo vận hành/}).click();
  await page.getByRole("button", {name: "SOT / duyệt"}).click();
  await expect(page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"})).toHaveClass(/open/);
  await expect(page.getByRole("complementary", {name: "Template registry"})).not.toHaveClass(/open/);
  await page.waitForTimeout(250);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({path: "test-results/tip009-documents-mobile-rail.png", fullPage: true});
  await page.keyboard.press("Escape");
  await expect(page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"})).not.toHaveClass(/open/);
  await page.waitForTimeout(250);
  await page.screenshot({path: "test-results/tip009-documents-mobile.png", fullPage: true});
});
