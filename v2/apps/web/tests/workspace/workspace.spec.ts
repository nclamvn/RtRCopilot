import {test, expect, type Page} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {readFile} from "node:fs/promises";

async function createWorkspace(page: Page, name: string) {
  await page.goto("/workspace");
  await expect(page.getByRole("status").filter({hasText: "Simulation"}).first()).toBeVisible();
  await page.getByRole("button", {name: "New workspace", exact: false}).click();
  await page.getByLabel("Workspace name").fill(name);
  await page.getByRole("button", {name: "Create workspace", exact: true}).click();
  await expect(page.getByRole("heading", {name, exact: true})).toBeVisible();
}

test("REAL local API + deterministic model: source → brief → versioned revision → download → reload", async ({page}) => {
  await createWorkspace(page, "Field study");
  await page.getByLabel("Source file", {exact: true}).setInputFiles("../../../docs/agent-workspace/fixtures/harbor-notes.md");
  await expect(page.locator(".aw-sources")).toContainText("harbor-notes.md");
  const composer = page.getByRole("textbox", {name: "Message", exact: true});
  await composer.fill("fixture:create");
  await composer.press("Enter");
  await expect(composer).toHaveValue("");
  await expect(page.getByLabel("Your message")).toHaveCount(1);
  await expect(page.getByLabel("Artifact preview")).toBeVisible();
  await expect(page.getByLabel("Artifact version")).toHaveValue("1");
  await expect(page.getByLabel("Run activity")).toContainText("Finished:");
  await expect(page.getByRole("button", {name: "Send", exact: false})).toBeVisible();
  await composer.fill("fixture:edit");
  await composer.press("Enter");
  await expect(page.getByLabel("Artifact version")).toHaveValue("2");
  await expect(page.getByLabel("Your message")).toHaveCount(2);
  await page.screenshot({path: "test-results/workspace/desktop-artifact.png"});
  const preview = await page.locator(".aw-artifact-content").innerText();
  expect(preview.length).toBeGreaterThan(20);
  expect(preview).toContain("24,750"); expect(preview).toContain("Giữ nguyên số liệu và dấu tiếng Việt");
  const download = page.waitForEvent("download");
  await page.getByRole("link", {name: "Download", exact: true}).click();
  const downloaded = await download;
  expect(downloaded.suggestedFilename()).toMatch(/\.md$/);
  const downloadedText = await readFile((await downloaded.path())!, "utf8");
  expect(downloadedText).toContain("24,750"); expect(downloadedText).toContain("Giữ nguyên số liệu và dấu tiếng Việt"); expect(downloadedText).toContain("## Revision");
  await page.reload();
  await expect(page.getByLabel("Your message")).toHaveCount(2);
  await expect(page.locator(".aw-sources")).toContainText("harbor-notes.md");
  await page.getByRole("button", {name: "Outputs", exact: false}).click();
  await page.locator(".aw-output-list button").first().click();
  await expect(page.getByLabel("Artifact version")).toHaveValue("2");
  await expect(page.locator(".aw-artifact-content")).toHaveText(preview, {useInnerText: true});
  await page.getByLabel("Artifact version").selectOption("1");
  await expect(page.getByLabel("Artifact version")).toHaveValue("1");
  await composer.fill("fixture:error"); await composer.press("Enter");
  await expect(page.locator(".aw-run-note")).toContainText("failed");
  await expect(page.getByLabel("Artifact preview")).toBeVisible();
});

test("REAL API scope + duplicate idempotency + replay cursor are enforced", async ({page, browser}) => {
  await createWorkspace(page, "Boundary check");
  const spaces = await (await page.request.get("/api/workspace/workspaces")).json();
  const workspaceId = spaces.items[0].id;
  const payload = {workspace_id: workspaceId, message: "fixture:chat", client_request_id: crypto.randomUUID()};
  const first = await (await page.request.post("/api/workspace/runs", {data: payload})).json();
  const second = await (await page.request.post("/api/workspace/runs", {data: payload})).json();
  expect(second.run_id).toBe(first.run_id);
  await expect.poll(async () => (await (await page.request.get(`/api/workspace/runs/${first.run_id}`)).json()).state).toBe("completed");
  const stream = await (await page.request.get(`/api/workspace/runs/${first.run_id}/events?after=0`)).text();
  const ids = [...stream.matchAll(/^id:\s*(\d+)/gm)].map(match => Number(match[1])); expect(ids.length).toBeGreaterThan(2);
  const cursor = ids[Math.floor(ids.length / 2)];
  const resumed = await (await page.request.get(`/api/workspace/runs/${first.run_id}/events?after=${cursor}`)).text();
  expect([...resumed.matchAll(/^id:\s*(\d+)/gm)].every(match => Number(match[1]) > cursor)).toBe(true);
  const outsider = await browser.newContext();
  await outsider.request.post("http://127.0.0.1:3110/api/workspace/session", {data: {}, headers: {origin: "http://127.0.0.1:3110"}});
  expect((await outsider.request.get(`http://127.0.0.1:3110/api/workspace/runs/${first.run_id}`)).status()).toBe(404);
  expect((await outsider.request.get(`http://127.0.0.1:3110/api/workspace/workspaces/${workspaceId}/files`)).status()).toBe(404);
  await outsider.close();
});

test("REAL API: closing/reloading the subscription does not cancel or redispatch", async ({page}) => {
  await createWorkspace(page, "Reconnect study");
  const submitted: string[] = [];
  page.on("request", request => {if (request.method() === "POST" && request.url().endsWith("/api/workspace/runs")) submitted.push(request.postData() ?? "");});
  await page.getByRole("textbox", {name: "Message", exact: true}).fill("fixture:slow");
  const ack = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/api/workspace/runs"));
  await page.getByRole("button", {name: "Send", exact: false}).click(); await ack;
  await expect.poll(() => submitted.length).toBe(1);
  await page.reload();
  await expect(page.getByLabel("Assistant message")).toHaveCount(1, {timeout: 20_000});
  expect(submitted.length).toBe(1);
  await expect(page.getByLabel("Your message")).toHaveCount(1);
});

test("REAL API cancel confirms terminal state and preserves workspace", async ({page}) => {
  await createWorkspace(page, "Stop study");
  await page.getByRole("textbox", {name: "Message", exact: true}).fill("fixture:slow");
  const ack = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/api/workspace/runs"));
  await page.getByRole("button", {name: "Send", exact: false}).click(); const result = await (await ack).json();
  await page.getByRole("button", {name: "Stop", exact: true}).click();
  await expect.poll(async () => (await (await page.request.get(`/api/workspace/runs/${result.run_id}`)).json()).state, {timeout: 15_000}).toBe("cancelled");
  await page.reload();
  await expect(page.getByRole("status").filter({hasText: "Stopped"})).toBeVisible();
});

test("REAL API + browser transport fault: a lost completed ACK reconciles without redispatch", async ({page}) => {
  await createWorkspace(page, "Lost response study");
  let dispatches = 0;
  await page.route("**/api/workspace/runs", async route => {
    if (route.request().method() !== "POST") return route.continue();
    dispatches++;
    const response = await route.fetch();
    const result = await response.json();
    await expect.poll(async () => (await (await page.request.get(`/api/workspace/runs/${result.run_id}`)).json()).state).toBe("completed");
    // Only the browser transport fails. The real local backend completed normally.
    await route.abort("failed");
  });
  await page.getByRole("textbox", {name: "Message", exact: true}).fill("fixture:chat");
  await page.getByRole("button", {name: "Send", exact: false}).click();
  await expect(page.getByLabel("Assistant message")).toHaveCount(1);
  await expect(page.getByLabel("Your message")).toHaveCount(1);
  await expect(page.locator(".aw-error")).toHaveCount(0);
  expect(dispatches).toBe(1);
});

test("UI-only unavailable status fixture is immediate and disables dispatch", async ({page}) => {
  await page.route("**/api/workspace/status", route => route.fulfill({json: {available: false, test_mode: false, model: null, reason: "No permitted model configured", recovery: "unavailable"}}));
  await page.goto("/workspace");
  await expect(page.getByRole("status").filter({hasText: "Model unavailable"})).toBeVisible();
  await expect(page.getByRole("button", {name: "Send", exact: false})).toBeDisabled();
});

test("mobile keyboard, plain-text upload rejection, viewport geometry and accessibility", async ({page}) => {
  await createWorkspace(page, "Accessible notes");
  await page.getByLabel("Source file", {exact: true}).setInputFiles({name: "binary.pdf", mimeType: "application/pdf", buffer: Buffer.from("not a supported source")});
  await expect(page.locator(".aw-error")).toContainText("TXT, Markdown, or CSV");
  await page.getByRole("button", {name: "Dismiss error"}).click();
  await page.setViewportSize({width: 390, height: 844});
  await expect(page.getByRole("textbox", {name: "Message", exact: true})).toBeVisible();
  const bounds = await page.locator(".aw-composer").boundingBox(); expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390); expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844);
  const message = page.getByRole("textbox", {name: "Message", exact: true}); await message.fill("First line"); await message.press("Shift+Enter"); await message.press("x"); await expect(message).toHaveValue("First line\nx");
  await message.press("Escape");
  const results = await new AxeBuilder({page}).include(".agent-workspace").analyze(); expect(results.violations).toEqual([]);
  await page.screenshot({path: "test-results/workspace/mobile-composer.png"});
});
