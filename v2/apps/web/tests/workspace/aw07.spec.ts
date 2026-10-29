import {test, expect, type Page} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {readFile} from "node:fs/promises";

async function create(page: Page, name: string) {
  await page.goto("/workspace"); await expect(page.getByRole("status").filter({hasText: "Simulation"}).first()).toBeVisible();
  const navigation = page.getByRole("button", {name: "Open navigation", exact: true}); if (await navigation.isVisible()) await navigation.click();
  await expect(page.getByRole("button", {name: "New workspace", exact: false})).toBeVisible();
  await page.getByRole("button", {name: "New workspace", exact: false}).click(); await page.getByLabel("Workspace name", {exact: true}).fill(name); await page.getByRole("button", {name: "Create workspace", exact: true}).click(); await expect(page.getByRole("heading", {name, exact: true})).toBeVisible();
  return (await (await page.request.get("/api/workspace/workspaces")).json()).items.find((item: {name: string}) => item.name === name).id as string;
}
async function setup(page: Page) {
  const navigation = page.getByRole("button", {name: "Open navigation", exact: true}); if (await navigation.isVisible()) await navigation.click();
  await page.getByRole("button", {name: "Model & setup", exact: true}).click(); await expect(page.getByRole("heading", {name: "Model & setup", exact: true})).toBeVisible();
}

test("REAL AW07 explicit diagnostics contains aggregate owner health, no synthetic private data and no provider calls", async ({page}) => {
  const canary = "SYNTHETIC-AW07-PRIVATE-50391"; const wid = await create(page, canary);
  expect((await page.request.post(`/api/workspace/workspaces/${wid}/files`, {data: {filename: `${canary}.txt`, content: canary, media_type: "text/plain"}})).ok()).toBe(true);
  expect((await page.request.post(`/api/workspace/workspaces/${wid}/artifacts`, {data: {title: canary, kind: "document", content: canary, request_id: crypto.randomUUID()}})).ok()).toBe(true);
  let diagnosticsRequests = 0, runRequests = 0; page.on("request", request => {if (request.url().endsWith("/api/workspace/diagnostics")) diagnosticsRequests++; if (request.url().endsWith("/api/workspace/runs")) runRequests++;});
  await setup(page); expect(diagnosticsRequests).toBe(0); await page.getByRole("button", {name: "Check local runtime"}).click(); await expect(page.getByText("0.1.0-aw08", {exact: true})).toBeVisible(); await expect(page.getByRole("definition").filter({hasText: /^python-source-[a-f0-9]{20}$/})).toBeVisible();
  const waiting = page.waitForEvent("download"); await page.getByRole("button", {name: "Download safe diagnostics"}).click(); const file = await waiting; expect(file.suggestedFilename()).toBe("agent-workspace-diagnostics.json"); const body = await readFile((await file.path())!, "utf8"); const health = JSON.parse(body);
  expect(Object.keys(health).sort()).toEqual(["application", "checks", "counts", "dependencies", "format", "recovery", "runtime"]); expect(health.counts).toEqual({workspaces: 1, files: 1, artifacts: 1, runs_active: 0}); expect(health.checks).toEqual({network_tested: false, real_ai_accepted: false}); expect(health.runtime.simulation).toBe(true); expect(body).not.toContain(canary); expect(body).not.toContain(wid); expect(diagnosticsRequests).toBe(2); expect(runRequests).toBe(0);
  await page.screenshot({path: "test-results/workspace/aw07-local-pilot.png"});
});

test("REAL AW07 diagnostics is authenticated and owner scoped; browser runtime mutations stay absent", async ({page, browser}) => {
  await create(page, "AW07 owner boundary"); const origin = new URL(page.url()).origin; const other = await browser.newContext({baseURL: origin, extraHTTPHeaders: {Origin: origin}});
  try {
    expect((await other.request.get("/api/workspace/diagnostics")).status()).toBe(401); const session = await other.request.post("/api/workspace/session"); expect(session.ok()).toBe(true); const health = await (await other.request.get("/api/workspace/diagnostics")).json(); expect(health.counts).toEqual({workspaces: 0, files: 0, artifacts: 0, runs_active: 0});
    for (const path of ["diagnostics", "backup", "restore", "preflight", "runtime/restart"]) expect((await page.request.post(`/api/workspace/${path}`, {data: {}})).status()).toBe(400);
  } finally {await other.close();}
});

test("AW07 injected API outage gives recovery guidance, retry works and composer draft survives", async ({page}) => {
  await create(page, "AW07 outage recovery"); const composer = page.getByRole("textbox", {name: "Message", exact: true}); await composer.fill("Synthetic draft kept through local diagnostics outage"); let offline = true;
  await page.route("**/api/workspace/diagnostics", async route => {if (offline) await route.fulfill({status: 503, contentType: "application/json", body: JSON.stringify({error: {code: "workspace_service_unavailable"}, private_log: "SYNTHETIC-PRIVATE-SERVER-PATH"})}); else await route.continue();});
  const localAlert = page.locator(".aw-local-pilot").getByRole("alert");
  await setup(page); await page.getByRole("button", {name: "Check local runtime"}).click(); await expect(localAlert).toContainText("Do not delete your data directory"); await expect(localAlert).not.toContainText("SYNTHETIC-PRIVATE-SERVER-PATH"); await page.getByText("Your first local project", {exact: true}).click(); await expect(page.getByText(/These commands copy scripted content/)).toBeVisible();
  offline = false; await page.getByRole("button", {name: "Check local runtime"}).click(); await expect(page.getByText("0.1.0-aw08", {exact: true})).toBeVisible(); await expect(localAlert).toHaveCount(0); await page.getByRole("button", {name: "Close outputs", exact: true}).click(); await expect(composer).toHaveValue("Synthetic draft kept through local diagnostics outage"); await expect(page.getByLabel("Your message")).toHaveCount(0);
});

test("REAL AW07 first-project guide keeps manual document creation and versioned export useful without dispatch", async ({page}) => {
  await create(page, "AW07 guided manual project"); let runs = 0; page.on("request", request => {if (request.method() === "POST" && request.url().endsWith("/api/workspace/runs")) runs++;});
  await setup(page); await page.getByText("Your first local project", {exact: true}).click(); await expect(page.getByText(/Without a model, manual documents and tables still work/)).toBeVisible(); await page.getByText("Before an upgrade or recovery", {exact: true}).click(); await expect(page.getByText(/Restore only to a new data directory/)).toBeVisible(); await page.getByRole("button", {name: "Close outputs", exact: true}).click();
  await page.getByRole("button", {name: "Outputs", exact: false}).click(); await page.getByRole("button", {name: "New document", exact: false}).click(); await page.getByLabel("Title", {exact: true}).fill("Offline handover"); await page.getByLabel("Markdown content", {exact: true}).fill("# Synthetic handover\n\nBatch 00831: 97.25 units."); await page.getByRole("button", {name: "Save first version"}).click(); await expect(page.getByLabel("Artifact version", {exact: true})).toHaveValue("1");
  await page.getByRole("tab", {name: "Edit", exact: true}).click(); await page.getByLabel("Edit Markdown text").fill("# Reviewed synthetic handover\n\nBatch 00831: 97.25 units. Reviewed locally."); await page.getByRole("button", {name: "Save new version"}).click(); await expect(page.getByLabel("Artifact version", {exact: true})).toHaveValue("2"); const waiting = page.waitForEvent("download"); await page.getByRole("link", {name: "Download", exact: true}).click(); const file = await waiting; expect(await readFile((await file.path())!, "utf8")).toContain("97.25 units. Reviewed locally."); expect(runs).toBe(0);
});

test("REAL AW07 mobile keyboard guide/check remains accessible, bounded and does not force onboarding", async ({page}) => {
  await page.setViewportSize({width: 390, height: 844}); await create(page, "AW07 small screen"); await expect(page.getByRole("heading", {name: "Local pilot", exact: true})).toHaveCount(0); await setup(page); const first = page.getByText("Your first local project", {exact: true}); await first.focus(); await page.keyboard.press("Enter"); await expect(page.getByText(/These commands copy scripted content/)).toBeVisible();
  const check = page.getByRole("button", {name: "Check local runtime"}); await check.focus(); await page.keyboard.press("Enter"); await expect(page.getByText("0.1.0-aw08", {exact: true})).toBeVisible(); expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true); expect((await new AxeBuilder({page}).include(".agent-workspace").analyze()).violations).toEqual([]); await page.getByRole("button", {name: "Close outputs", exact: true}).click(); await expect(page.getByRole("textbox", {name: "Message", exact: true})).toBeVisible();
});
