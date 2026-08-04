import {expect, Page, test} from "@playwright/test";
import {ids} from "./support/mocks";

const identity = {user_id: ids.requesterId, email: "admin@rtrobotics.com", display_name: "RtR Admin", roles: ["admin"]};
const subject = {user_id: ids.peerId, issuer: "https://accounts.example", email: "staff@rtrobotics.com", display_name: "RtR Staff", status: "active", security_version: 2, roles: ["staff"], groups: [], last_seen_at: "2026-08-04T08:00:00Z"};

async function shell(page: Page, authenticated = true) {
  await page.route("**/api/auth/me", route => authenticated ? route.fulfill({json: identity}) : route.fulfill({status: 401, json: {error: {code: "authentication_required", message: ""}, request_id: "req-auth"}}));
  await page.route("**/api/status", route => route.fulfill({json: {ok: true, status: "ready"}}));
  await page.route("**/api/ask/conversations**", route => route.fulfill({json: {items: [], next_cursor: null}}));
}

async function adminData(page: Page, bindingStatus = 200) {
  await page.route("**/api/governance/admin/**", async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (path.endsWith("/jobs/health")) return route.fulfill({json: {computed_at: "2026-08-04T08:00:00Z", families: [{family: "ingestion", job_counts: {completed: 8}, outbox_counts: {published: 8}, recent_failures: []}]}});
    if (path.endsWith("/subjects") && request.method() === "GET") return route.fulfill({json: [subject]});
    if (path.endsWith("/bindings")) {
      if (bindingStatus === 401) return route.fulfill({status: 401, json: {error: {code: "authentication_required", message: ""}, request_id: "req-stale"}});
      const body = request.postDataJSON(); expect(body).toEqual({binding: "role", operation: "assign", key: "curator", reason: "approved pilot duty"});
      return route.fulfill({json: {...subject, security_version: 3, roles: ["staff", "curator"]}});
    }
    if (path.endsWith("/research-sources") || path.endsWith("/settings")) return route.fulfill({json: []});
    return route.fulfill({status: 404, json: {error: {code: "not_found", message: ""}, request_id: "req-admin"}});
  });
}

test("anonymous admin loads no governance data", async ({page}) => {
  await shell(page, false); let adminCalls = 0;
  await page.route("**/api/governance/admin/**", route => {adminCalls += 1; return route.abort();});
  await page.goto("/admin");
  await expect(page.getByRole("heading", {name: "Cần đăng nhập công ty"})).toBeVisible();
  expect(adminCalls).toBe(0);
});

test("admin changes one binding and renders server-authoritative security version", async ({page}) => {
  await shell(page); await adminData(page); await page.goto("/admin");
  await page.getByRole("button", {name: /Tài khoản/}).click();
  await page.getByText("RtR Staff", {exact: true}).first().click();
  await page.getByLabel("Khóa role hoặc group").fill("curator");
  await page.getByLabel(/Lý do thay đổi/).fill("approved pilot duty");
  await page.getByRole("button", {name: "Áp dụng thay đổi"}).click();
  await expect(page.getByText("Đã lưu · audit trail đã được tạo")).toBeVisible();
  await expect(page.getByText("security v3")).toBeVisible();
  await page.screenshot({path: "test-results/tip023-admin-desktop.png", fullPage: true});
});

test("401 during an admin mutation revokes the visible workspace", async ({page}) => {
  await shell(page); await adminData(page, 401); await page.goto("/admin");
  await page.getByRole("button", {name: /Tài khoản/}).click();
  await page.getByText("RtR Staff", {exact: true}).first().click();
  await page.getByLabel("Khóa role hoặc group").fill("curator");
  await page.getByLabel(/Lý do thay đổi/).fill("approved pilot duty");
  await page.getByRole("button", {name: "Áp dụng thay đổi"}).click();
  await expect(page.getByRole("heading", {name: "Cần đăng nhập công ty"})).toBeVisible();
  await expect(page.locator(".admin-workspace")).toHaveCount(0);
});

test("admin control spine remains balanced at 360px", async ({page}) => {
  await shell(page); await adminData(page); await page.setViewportSize({width: 360, height: 800}); await page.goto("/admin");
  await expect(page.locator(".admin-ledger article")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({path: "test-results/tip023-admin-mobile.png", fullPage: true});
});
