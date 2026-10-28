import {test, expect, type Page} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function create(page: Page, name: string) {
  await page.goto("/workspace"); await expect(page.getByRole("status").filter({hasText: "Simulation"}).first()).toBeVisible();
  await page.getByRole("button", {name: "New workspace", exact: false}).click(); await page.getByLabel("Workspace name").fill(name); await page.getByRole("button", {name: "Create workspace", exact: true}).click(); await expect(page.getByRole("heading", {name, exact: true})).toBeVisible();
  const spaces = await (await page.request.get("/api/workspace/workspaces")).json(); return spaces.items.find((item: {name: string}) => item.name === name).id as string;
}
async function send(page: Page, command: string) {
  const composer = page.getByRole("textbox", {name: "Message", exact: true}); await composer.fill(command);
  await expect(page.getByRole("button", {name: "Send", exact: false})).toBeVisible();
  const ack = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/api/workspace/runs")); await composer.press("Enter"); const result = await (await ack).json(); expect(result.run_id).toBeTruthy(); return result.run_id as string;
}
async function terminal(page: Page, id: string, state = "completed") {await expect.poll(async () => (await (await page.request.get(`/api/workspace/runs/${id}`)).json()).state, {timeout: 25_000}).toBe(state);}
async function openControl(page: Page, name: "Memory" | "Connections" | "Schedules") {
  if (await page.getByRole("button", {name: "Open navigation", exact: true}).isVisible()) await page.getByRole("button", {name: "Open navigation", exact: true}).click();
  await page.getByRole("button", {name, exact: true}).click(); await expect(page.getByRole("heading", {name, exact: true})).toBeVisible();
}
async function grant(page: Page) {await openControl(page, "Connections"); await page.getByRole("button", {name: "Grant fixture permission"}).click(); await expect(page.getByText("Permission granted for this workspace", {exact: true})).toBeVisible();}
async function closePanel(page: Page) {await page.getByRole("button", {name: "Close outputs", exact: true}).click();}

test("REAL AW03 explicit memory create/edit/delete, model tool read and workspace isolation", async ({page}) => {
  const id = await create(page, "Memory workbench"); await openControl(page, "Memory");
  await page.getByLabel("Remembered note", {exact: true}).fill("Remember user-selected detail: Việt Nam 24750 units."); await page.getByRole("button", {name: "Save memory", exact: true}).click(); await expect(page.getByLabel("Saved memories")).toContainText("Việt Nam 24750 units.");
  await closePanel(page); const first = await send(page, "fixture:memory"); await terminal(page, first); await expect(page.getByLabel("Assistant message").last()).toContainText("24750");
  await openControl(page, "Memory"); await page.getByRole("button", {name: "Edit memory", exact: true}).click(); await page.getByLabel("Edit remembered note").fill("Remember user-selected detail: Việt Nam 24751 units."); await page.getByRole("button", {name: "Save memory changes"}).click(); await expect(page.getByLabel("Saved memories")).toContainText("24751");
  const memories = await (await page.request.get(`/api/workspace/workspaces/${id}/memory`)).json(); expect(memories.items).toHaveLength(1); expect(memories.items[0].version).toBe(2);
  await page.getByRole("button", {name: "Delete memory", exact: true}).click(); await expect(page.getByLabel("Confirm memory deletion")).toBeVisible(); await page.getByRole("button", {name: "Confirm delete memory"}).click(); await expect(page.getByText(/No saved memories/)).toBeVisible();
  await page.reload(); await openControl(page, "Memory"); await expect(page.getByText(/No saved memories/)).toBeVisible(); await closePanel(page); const second = await send(page, "fixture:memory"); await terminal(page, second); await expect(page.getByLabel("Assistant message").last()).not.toContainText("24750"); await expect(page.getByLabel("Assistant message").last()).not.toContainText("24751");
  const other = await create(page, "Separate memory workspace"); await openControl(page, "Memory"); await expect(page.getByText(/No saved memories/)).toBeVisible(); expect((await (await page.request.get(`/api/workspace/workspaces/${other}/memory`)).json()).items).toEqual([]);
});

test("REAL AW03 fixture MCP read needs one grant; pending approval survives reload and produces one receipt", async ({page}) => {
  const id = await create(page, "Connection workbench"); await grant(page); await closePanel(page);
  for (let i = 0; i < 2; i++) {const rid = await send(page, "fixture:mcp-read"); await terminal(page, rid); await expect(page.getByLabel("Pending action approval")).toHaveCount(0);}
  expect((await (await page.request.get(`/api/workspace/workspaces/${id}/approvals`)).json()).items).toEqual([]);
  const rid = await send(page, "fixture:mcp-effect"); await expect(page.getByLabel("Pending action approval")).toBeVisible();
  const pending = (await (await page.request.get(`/api/workspace/workspaces/${id}/approvals`)).json()).items.find((x: {status: string}) => x.status === "pending"); expect(pending.run_id).toBe(rid);
  expect((await page.request.post(`/api/workspace/approvals/${pending.id}/resolve`, {data: {approved: true, decision: "approve", request_id: crypto.randomUUID()}})).status()).toBe(422);
  let extraDispatches = 0; page.on("request", request => {if (request.method() === "POST" && request.url().endsWith("/api/workspace/runs")) extraDispatches++;});
  await page.reload(); await expect(page.getByLabel("Pending action approval")).toBeVisible(); expect(extraDispatches).toBe(0); await page.screenshot({path: "test-results/workspace/aw03-desktop-approval.png"});
  await openControl(page, "Connections");
  await page.getByRole("button", {name: "Approve simulated action"}).click(); await terminal(page, rid); expect(extraDispatches).toBe(0);
  await expect(page.getByRole("heading", {name: "Connections", exact: true})).toBeVisible();
  await expect.poll(async () => (await (await page.request.get(`/api/workspace/workspaces/${id}/effects`)).json()).items.filter((x: {status: string}) => x.status === "completed").length).toBe(1);
  // Re-delivering approval cannot cause a second simulated send, regardless of response status.
  await page.request.post(`/api/workspace/approvals/${pending.id}/resolve`, {data: {decision: "approve", request_id: crypto.randomUUID()}}); expect((await (await page.request.get(`/api/workspace/workspaces/${id}/effects`)).json()).items).toHaveLength(1);
  await expect(page.getByLabel("Action history")).toContainText("Receipt confirmed"); await expect(page.getByLabel("Action history")).not.toContainText("Outcome unknown"); await page.screenshot({path: "test-results/workspace/aw03-desktop-receipt.png"});
});

test("REAL AW03 revocation invalidates pending action; rejection and memory deletion never send", async ({page}) => {
  const id = await create(page, "Revocation workbench"); await grant(page); await closePanel(page); const rid = await send(page, "fixture:mcp-effect"); await expect(page.getByLabel("Pending action approval")).toBeVisible();
  const pending = (await (await page.request.get(`/api/workspace/workspaces/${id}/approvals`)).json()).items.find((x: {status: string}) => x.status === "pending");
  await openControl(page, "Connections"); await page.getByRole("button", {name: "Revoke fixture permission"}).click(); await expect(page.getByText("Not connected", {exact: true})).toBeVisible();
  expect((await page.request.post(`/api/workspace/approvals/${pending.id}/resolve`, {data: {decision: "approve", request_id: crypto.randomUUID()}})).status()).toBeGreaterThanOrEqual(400); await terminal(page, rid, "cancelled"); expect((await (await page.request.get(`/api/workspace/workspaces/${id}/effects`)).json()).items).toEqual([]);
  await page.getByRole("button", {name: "Grant fixture permission"}).click(); await closePanel(page); const rejectRun = await send(page, "fixture:mcp-effect"); await expect(page.getByLabel("Pending action approval")).toBeVisible(); await page.getByRole("button", {name: "Reject action", exact: true}).click(); await terminal(page, rejectRun, "failed"); expect((await (await page.request.get(`/api/workspace/workspaces/${id}/effects`)).json()).items).toEqual([]);
  await openControl(page, "Memory"); await page.getByLabel("Remembered note", {exact: true}).fill("Transient private fixture 62019"); await page.getByRole("button", {name: "Save memory", exact: true}).click(); await expect(page.getByLabel("Saved memories")).toContainText("62019"); await closePanel(page); const memoryRun = await send(page, "fixture:memory-wait"); await expect(page.getByLabel("Pending action approval")).toBeVisible();
  await openControl(page, "Memory"); await page.getByRole("button", {name: "Delete memory", exact: true}).click(); await page.getByRole("button", {name: "Confirm delete memory"}).click(); await terminal(page, memoryRun, "cancelled"); expect((await (await page.request.get(`/api/workspace/workspaces/${id}/effects`)).json()).items).toEqual([]);
});

test("REAL AW03 manual clock pause/resume/cancel and repeated ticks dispatch each schedule once", async ({page}) => {
  const id = await create(page, "Schedule workbench"); await openControl(page, "Schedules"); await page.getByLabel("One-time task", {exact: true}).fill("fixture:chat"); await page.getByLabel("Due at simulation second").fill("60"); await page.getByRole("button", {name: "Save one-time task"}).click(); await expect(page.getByLabel("Scheduled tasks")).toContainText("fixture:chat");
  await page.getByRole("button", {name: "Pause task", exact: true}).click(); await expect(page.getByLabel("Scheduled tasks")).toContainText("paused"); await page.getByRole("button", {name: "Advance simulation clock"}).click(); await expect(page.getByText("Simulation clock: 60 s", {exact: true})).toBeVisible(); expect((await (await page.request.get(`/api/workspace/workspaces/${id}/messages`)).json()).items).toEqual([]);
  await page.getByRole("button", {name: "Resume task", exact: true}).click(); await page.getByRole("button", {name: "Advance simulation clock"}).click(); await expect(page.getByLabel("Scheduled tasks")).toContainText("dispatched");
  let schedules = await (await page.request.get(`/api/workspace/workspaces/${id}/schedules`)).json(); const runId = schedules.items[0].run_id; expect(runId).toBeTruthy(); await terminal(page, runId);
  await Promise.all([1, 2].map(() => page.request.post(`/api/workspace/workspaces/${id}/clock/tick`, {data: {target: 60, request_id: crypto.randomUUID()}}))); schedules = await (await page.request.get(`/api/workspace/workspaces/${id}/schedules`)).json(); expect(schedules.items[0].run_id).toBe(runId); const history = await (await page.request.get(`/api/workspace/workspaces/${id}/messages`)).json(); expect(history.items.filter((x: {role: string}) => x.role === "user")).toHaveLength(1);
  await page.getByLabel("One-time task", {exact: true}).fill("fixture:chat"); await page.getByLabel("Due at simulation second").fill("120"); await page.getByRole("button", {name: "Save one-time task"}).click(); await page.getByRole("button", {name: "Cancel task", exact: true}).click(); await expect(page.getByLabel("Scheduled tasks")).toContainText("cancelled"); await page.getByLabel("Advance clock to second").fill("120"); await page.getByRole("button", {name: "Advance simulation clock"}).click(); expect((await (await page.request.get(`/api/workspace/workspaces/${id}/messages`)).json()).items.filter((x: {role: string}) => x.role === "user")).toHaveLength(1);
  // The server's finite manual clock supports fractional seconds; UI must not impose an integer-only hidden restriction.
  await page.getByLabel("One-time task", {exact: true}).fill("fixture:chat"); await page.getByLabel("Due at simulation second").fill("120.25"); await page.getByRole("button", {name: "Save one-time task"}).click(); await expect(page.getByLabel("Scheduled tasks")).toContainText("Due at 120.25 s"); await page.getByLabel("Advance clock to second").fill("120.25"); await page.getByRole("button", {name: "Advance simulation clock"}).click(); await expect(page.getByText("Simulation clock: 120.25 s", {exact: true})).toBeVisible();
  await page.setViewportSize({width: 390, height: 844}); await page.getByRole("button", {name: "Close outputs", exact: true}).scrollIntoViewIfNeeded(); await page.screenshot({path: "test-results/workspace/aw03-mobile-schedules.png"}); expect((await new AxeBuilder({page}).include(".agent-workspace").analyze()).violations).toEqual([]); await page.reload(); await openControl(page, "Schedules"); await expect(page.getByText("Simulation clock: 120.25 s", {exact: true})).toBeVisible();
});

test("REAL AW03 new control APIs deny foreign owner IDs and do not expose a generic MCP executor", async ({page, browser}) => {
  const id = await create(page, "Control boundary workbench"); const outsider = await browser.newContext(); await outsider.request.post("http://127.0.0.1:3110/api/workspace/session", {data: {}, headers: {origin: "http://127.0.0.1:3110"}});
  for (const family of ["memory", "schedules", "connection", "approvals", "effects"]) expect((await outsider.request.get(`http://127.0.0.1:3110/api/workspace/workspaces/${id}/${family}`)).status()).toBe(404);
  expect((await page.request.post(`/api/workspace/workspaces/${id}/connection`, {data: {enabled: true, expected_revision: 0, request_id: crypto.randomUUID(), command: "cat ~/.env"}})).status()).toBe(422);
  expect((await page.request.post("/api/workspace/mcp/execute", {data: {command: "anything"}})).status()).toBe(400); await outsider.close();
});
