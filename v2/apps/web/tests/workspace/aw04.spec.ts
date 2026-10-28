import {test, expect, type Page} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {inflateRawSync} from "node:zlib";
import {readFile, unlink} from "node:fs/promises";

async function create(page: Page, name: string) {
  await page.goto("/workspace"); await expect(page.getByRole("status").filter({hasText: "Simulation"}).first()).toBeVisible();
  await page.getByRole("button", {name: "New workspace", exact: false}).click(); await page.getByLabel("Workspace name").fill(name); await page.getByRole("button", {name: "Create workspace", exact: true}).click(); await expect(page.getByRole("heading", {name, exact: true})).toBeVisible();
  const spaces = await (await page.request.get("/api/workspace/workspaces")).json(); return spaces.items.find((item: {name: string}) => item.name === name).id as string;
}
async function open(page: Page, name: "Model & setup" | "Workspace data") {
  if (await page.getByRole("button", {name: "Open navigation", exact: true}).isVisible()) await page.getByRole("button", {name: "Open navigation", exact: true}).click();
  await page.getByRole("button", {name, exact: true}).click(); await expect(page.getByRole("heading", {name, exact: true})).toBeVisible();
}
function zipEntries(bytes: Buffer): Record<string, Buffer> {
  const entries: Record<string, Buffer> = {}; const end = bytes.lastIndexOf(Buffer.from([80, 75, 5, 6])); expect(end).toBeGreaterThanOrEqual(0); let offset = bytes.readUInt32LE(end + 16); const count = bytes.readUInt16LE(end + 10);
  for (let index = 0; index < count; index++) {expect(bytes.readUInt32LE(offset)).toBe(0x02014b50); const method = bytes.readUInt16LE(offset + 10); const size = bytes.readUInt32LE(offset + 20); const length = bytes.readUInt16LE(offset + 28); const extra = bytes.readUInt16LE(offset + 30); const comment = bytes.readUInt16LE(offset + 32); const local = bytes.readUInt32LE(offset + 42); const name = bytes.subarray(offset + 46, offset + 46 + length).toString(); expect(name).not.toMatch(/(^\/|\.\.)/); const start = local + 30 + bytes.readUInt16LE(local + 26) + bytes.readUInt16LE(local + 28); const body = bytes.subarray(start, start + size); entries[name] = method === 8 ? inflateRawSync(body) : body; offset += 46 + length + extra + comment;}
  return entries;
}

test("REAL local API AW04 readiness is nonsecret, explicitly simulated and network-free", async ({page}) => {
  await create(page, "Setup workbench"); await open(page, "Model & setup"); await expect(page.getByRole("heading", {name: "Simulation, not a live AI"})).toBeVisible(); await expect(page.getByText(/not real AI responses/)).toBeVisible();
  const result = await (await page.request.get("/api/workspace/readiness")).json(); expect(result.test_mode).toBe(true); expect(result.provider.storage).toBe(false); expect(result).not.toHaveProperty("api_key"); expect(result.provider).not.toHaveProperty("api_key"); expect(await page.getByLabel("Model setup").getByRole("textbox").count()).toBe(0);
  expect((await page.request.post("/api/workspace/configure", {data: {api_key: "synthetic-never-forward"}})).status()).toBe(400); await expect(page).toHaveTitle("Agent Workspace");
});

test("UI-only synthetic unavailable/ready statuses guide terminal setup and natural prompts, not AI quality", async ({page}) => {
  await create(page, "Readiness views"); let ready = false;
  await page.route("**/api/workspace/readiness", route => route.fulfill({json: {available: ready, test_mode: false, model: ready ? "synthetic-provider-model" : null, reason: ready ? null : "Credentials missing", recovery: "Configure in your local terminal.", provider: {configured: ready, endpoint: "OpenAI public API", external_processing: ready, storage: false, transport: "responses", requires_restart: true}, setup_command: "workspace configure"}}));
  await open(page, "Model & setup"); await expect(page.getByText("Missing or incomplete")).toBeVisible(); await expect(page.getByText(/Never paste a key/)).toBeVisible(); expect(await page.getByLabel("Model setup").getByRole("textbox").count()).toBe(0);
  ready = true; await page.getByRole("button", {name: "Check readiness again"}).click(); await expect(page.getByRole("heading", {name: "Model ready", exact: true})).toBeVisible(); await page.getByRole("button", {name: "Close outputs", exact: true}).click(); await page.getByRole("button", {name: "Create a brief from my files"}).click(); await expect(page.getByRole("textbox", {name: "Message", exact: true})).toHaveValue("Create a concise Markdown brief from my source files.");
});

test("REAL local API AW04 ZIP readback includes source originals and consistent artifact versions", async ({page}, testInfo) => {
  const id = await create(page, "Export workbench");
  const source = "Synthetic original Δ 24750\n";
  const file = await page.request.post(`/api/workspace/workspaces/${id}/files`, {data: {filename: "original.txt", content: source, media_type: "text/plain"}}); expect(file.ok()).toBe(true);
  const first = await (await page.request.post(`/api/workspace/workspaces/${id}/artifacts`, {data: {title: "Export note", kind: "document", content: "# First\n24750", request_id: crypto.randomUUID()}})).json();
  expect((await page.request.post(`/api/workspace/artifacts/${first.id}/revisions`, {data: {expected_version: 1, content: "# Second\n24751", request_id: crypto.randomUUID()}})).ok()).toBe(true);
  await page.request.post(`/api/workspace/workspaces/${id}/memory`, {data: {content: "Explicit export note 24752", request_id: crypto.randomUUID()}});
  await open(page, "Workspace data"); const pending = page.waitForEvent("download"); await page.getByRole("button", {name: "Download workspace ZIP"}).click(); const download = await pending; const path = testInfo.outputPath("workspace-export.zip"); await download.saveAs(path); const entries = zipEntries(await readFile(path)); await unlink(path);
  expect(entries["manifest.json"]).toBeTruthy(); const texts = Object.values(entries).map(value => value.toString()); expect(texts).toContain(source); expect(texts).toContain("# First\n24750"); expect(texts).toContain("# Second\n24751"); expect(texts.join("\n")).toContain("Explicit export note 24752"); expect(texts.join("\n")).not.toMatch(/session_hash|WORKSPACE_API_KEY|api_key/); await expect(page.getByText(/consistent snapshot/)).toBeVisible();
});

test("REAL local API AW04 confirmed idle deletion fences cached data, foreign scope and reload", async ({page, browser}) => {
  const other = await create(page, "Keep this workspace"); const id = await create(page, "Delete this notebook");
  const item = await (await page.request.post(`/api/workspace/workspaces/${id}/artifacts`, {data: {title: "Private draft", kind: "document", content: "Synthetic private 97120", request_id: crypto.randomUUID()}})).json();
  await page.evaluate(({id, other, artifactId}) => {localStorage.setItem(`agent-workspace:artifact-draft:${artifactId}`, "private draft"); localStorage.setItem(`agent-workspace:new-draft:${id}:document`, "private new draft"); localStorage.setItem(`agent-workspace:run:${id}`, "stale-run"); localStorage.setItem(`agent-workspace:new-draft:${other}:document`, "keep draft");}, {id, other, artifactId: item.id});
  const origin = new URL(page.url()).origin; const stranger = await browser.newContext({baseURL: origin, extraHTTPHeaders: {origin}}); expect((await stranger.request.post("/api/workspace/session", {data: {}})).ok()).toBe(true); expect((await stranger.request.get(`/api/workspace/workspaces/${id}/delete-preview`)).status()).toBe(404); expect((await stranger.request.get(`/api/workspace/workspaces/${id}/export`)).status()).toBe(404); await stranger.close();
  await open(page, "Workspace data"); await page.getByRole("button", {name: "Review workspace deletion"}).click(); await expect(page.getByLabel("Confirm workspace deletion")).toBeVisible(); await expect(page.getByRole("button", {name: "Permanently delete workspace"})).toBeDisabled(); await page.getByLabel("Type Delete this notebook to confirm").fill("Delete this notebook"); await page.getByRole("button", {name: "Permanently delete workspace"}).click(); await expect(page.getByText(/Workspace deleted\. Its application data/)).toBeVisible();
  expect((await page.request.get(`/api/workspace/artifacts/${item.id}`)).status()).toBe(404); expect((await page.request.get(`/api/workspace/workspaces/${id}/messages`)).status()).toBe(404);
  const cache = await page.evaluate(({id, other, artifactId}) => ({artifact: localStorage.getItem(`agent-workspace:artifact-draft:${artifactId}`), draft: localStorage.getItem(`agent-workspace:new-draft:${id}:document`), run: localStorage.getItem(`agent-workspace:run:${id}`), other: localStorage.getItem(`agent-workspace:new-draft:${other}:document`)}), {id, other, artifactId: item.id}); expect(cache).toEqual({artifact: null, draft: null, run: null, other: "keep draft"});
  await page.reload(); await expect(page.getByRole("button", {name: "Delete this notebook", exact: false})).toHaveCount(0); await expect(page.getByRole("textbox", {name: "Message", exact: true})).toHaveValue("");
});

test("REAL local API AW04 busy deletion stays blocked with recovery; mobile setup remains accessible", async ({page}) => {
  const id = await create(page, "Busy workbench"); const permission = await page.request.post(`/api/workspace/workspaces/${id}/connection`, {data: {enabled: true, expected_revision: 0, request_id: crypto.randomUUID()}}); expect(permission.ok()).toBe(true); const run = await (await page.request.post("/api/workspace/runs", {data: {workspace_id: id, message: "fixture:mcp-effect", client_request_id: crypto.randomUUID()}})).json(); await expect.poll(async () => (await (await page.request.get(`/api/workspace/runs/${run.run_id}`)).json()).state).toBe("waiting_approval");
  await open(page, "Workspace data"); await page.getByRole("button", {name: "Review workspace deletion"}).click(); await expect(page.getByText(/Deletion is blocked/)).toBeVisible(); expect(await page.getByRole("button", {name: "Permanently delete workspace"}).count()).toBe(0); await page.getByRole("button", {name: "Review activity and recovery"}).click(); await expect(page.getByRole("heading", {name: "Connections", exact: true})).toBeVisible();
  await page.request.post(`/api/workspace/runs/${run.run_id}/cancel`, {data: {}});
  await page.getByRole("button", {name: "Close outputs", exact: true}).click(); await page.setViewportSize({width: 390, height: 844}); await open(page, "Model & setup"); await expect(page.getByRole("heading", {name: "Model & setup", exact: true})).toBeInViewport(); await page.getByLabel("Model setup").evaluate(element => element.parentElement!.scrollTo(0, 10000)); await expect(page.getByRole("button", {name: "Close outputs", exact: true})).toBeInViewport(); expect((await new AxeBuilder({page}).include(".agent-workspace").analyze()).violations).toEqual([]);
});

test("REAL local API AW04 late deletion ACK cannot replace another selected workspace or resurrect drafts", async ({page}) => {
  const other = await create(page, "Late ACK survivor"); const id = await create(page, "Late ACK delete"); let release: (() => void) | undefined; let deleted = false;
  await page.route(`**/api/workspace/workspaces/${id}/delete`, async route => {const response = await route.fetch(); deleted = true; await new Promise<void>(resolve => {release = resolve;}); await route.fulfill({response});});
  await open(page, "Workspace data"); await page.getByRole("button", {name: "Review workspace deletion"}).click(); await page.getByLabel("Type Late ACK delete to confirm").fill("Late ACK delete"); await page.getByRole("button", {name: "Permanently delete workspace"}).click(); await expect.poll(() => deleted).toBe(true);
  await page.getByRole("button", {name: "Late ACK survivor", exact: false}).click(); await expect(page.getByRole("heading", {name: "Late ACK survivor", exact: true})).toBeVisible(); await page.getByRole("textbox", {name: "Message", exact: true}).fill("Keep this survivor draft"); release!();
  await expect.poll(async () => (await (await page.request.get("/api/workspace/workspaces")).json()).items.some((item: {id: string}) => item.id === id)).toBe(false); await expect(page.getByRole("button", {name: "Late ACK delete", exact: false})).toHaveCount(0); await expect(page.getByRole("heading", {name: "Late ACK survivor", exact: true})).toBeVisible(); await expect(page.getByRole("textbox", {name: "Message", exact: true})).toHaveValue("Keep this survivor draft"); expect(await page.evaluate(() => localStorage.getItem("agent-workspace:selected"))).toBe(other);
});
