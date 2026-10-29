import {test, expect, type Page} from "@playwright/test";

// Contractor probe, not a natural model or human productivity benchmark.
// Raw replacement is a precomputed complete string; focused/grid replacements
// are precomputed local snippets. Report this asymmetry, never infer human time.
async function workspace(page: Page) {
  await page.goto("/workspace");
  await expect(page.getByRole("status").filter({hasText: "Simulation"}).first()).toBeVisible();
  const navigation = page.getByRole("button", {name: "Open navigation", exact: true});
  if (await navigation.isVisible()) await navigation.click();
  await page.getByRole("button", {name: "New workspace", exact: false}).click();
  const name = "AW08 comparison " + crypto.randomUUID();
  await page.getByLabel("Workspace name", {exact: true}).fill(name);
  await page.getByRole("button", {name: "Create workspace", exact: true}).click();
  await expect(page.getByRole("heading", {name, exact: true})).toBeVisible();
  const rows = await (await page.request.get("/api/workspace/workspaces")).json();
  return rows.items.find((row: {name: string}) => row.name === name).id as string;
}

async function artifact(page: Page, wid: string, title: string, kind: string, content: string) {
  const result = await page.request.post(`/api/workspace/workspaces/${wid}/artifacts`, {data: {title, kind, content, request_id: crypto.randomUUID()}});
  expect(result.ok()).toBe(true);
  return result.json();
}

async function open(page: Page, title: string) {
  await page.reload();
  await expect(page.getByRole("status").filter({hasText: "Simulation"}).first()).toBeVisible();
  await page.getByRole("button", {name: "Outputs", exact: false}).click();
  await page.getByRole("button", {name: new RegExp("^" + title)}).click();
  await page.getByRole("tab", {name: "Edit", exact: true}).click();
}

test("Contractor AW08 raw vs focused paragraph: exact retained content, declared actions and typed bytes", async ({page}, info) => {
  const wid = await workspace(page);
  const old = "A synthetic programme starts on Monday; batch 000731 keeps 12.340 kg.";
  const replacement = "A synthetic programme starts on Tuesday; batch 000731 keeps 12.340 kg.";
  const original = "# Programme notes\n\n" + old + "\n\nTiếng Việt: phần này không thay đổi.\n\nControl value: 1,25 m; source ID 008491.\n";
  const desired = original.replace(old, replacement);
  const raw = await artifact(page, wid, "Raw paragraph comparison", "document", original);
  const focused = await artifact(page, wid, "Focused paragraph comparison", "document", original);
  await open(page, "Raw paragraph comparison");
  const rawStart = performance.now();
  await page.getByRole("button", {name: "Raw Markdown", exact: true}).click();
  await page.getByLabel("Edit Markdown text", {exact: true}).fill(desired);
  await page.getByRole("button", {name: "Save new version", exact: true}).click();
  await expect(page.getByLabel("Artifact version", {exact: true})).toHaveValue("2");
  const rawMs = performance.now() - rawStart;
  await open(page, "Focused paragraph comparison");
  const focusedStart = performance.now();
  await page.getByRole("button", {name: "Focused edit", exact: true}).click();
  await page.getByLabel("Paragraph to edit", {exact: true}).selectOption({index: 2});
  await page.getByLabel("Replacement text", {exact: true}).fill(replacement);
  await page.getByRole("button", {name: "Apply to draft", exact: true}).click();
  await page.getByRole("button", {name: "Save new version", exact: true}).click();
  await expect(page.getByLabel("Artifact version", {exact: true})).toHaveValue("2");
  const focusedMs = performance.now() - focusedStart;
  for (const row of [raw, focused]) {
    expect((await (await page.request.get(`/api/workspace/artifacts/${row.id}`)).json()).content).toBe(desired);
    expect((await (await page.request.get(`/api/workspace/artifacts/${row.id}?version=1`)).json()).content).toBe(original);
  }
  const measurement = {task: "one exact paragraph revision", raw: {actions: 3, typed_utf8_bytes: Buffer.byteLength(desired), scripted_ms: rawMs}, focused: {actions: 5, typed_utf8_bytes: Buffer.byteLength(replacement), scripted_ms: focusedMs}, invariant: "same exact saved v2 and untouched v1", provenance: "one warm automated browser sample, both text variants precomputed; raw uses full-document fill, not a human timing or proof that snippets cannot be edited in raw mode"};
  await info.attach("aw08-comparison-document", {body: JSON.stringify(measurement, null, 2), contentType: "application/json"});
  console.log("AW08_COMPARISON " + JSON.stringify(measurement));
});

test("Contractor AW08 raw vs grid: literal values, equal selected edits and bounded field operations", async ({page}, info) => {
  const wid = await workspace(page);
  const original = 'ID,Quantity,Note\n000731,12.340 kg,Tiếng Việt\n000732,"1,25 m",Pending\n000733,-4.50,=SUM(A1:A2)\n';
  const desired = original.replace("12.340 kg", "42.750 kg").replace("Pending", "Đã rà soát");
  const raw = await artifact(page, wid, "Raw table comparison", "table", original);
  const grid = await artifact(page, wid, "Grid table comparison", "table", original);
  await open(page, "Raw table comparison");
  const rawStart = performance.now();
  await page.getByRole("button", {name: "Raw CSV", exact: true}).click();
  await page.getByLabel("Edit CSV text", {exact: true}).fill(desired);
  await page.getByRole("button", {name: "Save new version", exact: true}).click();
  await expect(page.getByLabel("Artifact version", {exact: true})).toHaveValue("2");
  const rawMs = performance.now() - rawStart;
  await open(page, "Grid table comparison");
  const gridStart = performance.now();
  await page.getByLabel("Row 2, column 2", {exact: true}).fill("42.750 kg");
  await page.getByLabel("Row 3, column 3", {exact: true}).fill("Đã rà soát");
  await page.getByRole("button", {name: "Save new version", exact: true}).click();
  await expect(page.getByLabel("Artifact version", {exact: true})).toHaveValue("2");
  const gridMs = performance.now() - gridStart;
  for (const row of [raw, grid]) {
    expect((await (await page.request.get(`/api/workspace/artifacts/${row.id}`)).json()).content).toBe(desired);
    expect((await (await page.request.get(`/api/workspace/artifacts/${row.id}?version=1`)).json()).content).toBe(original);
  }
  const measurement = {task: "two string cell revisions", raw: {actions: 3, typed_utf8_bytes: Buffer.byteLength(desired), scripted_ms: rawMs}, grid: {actions: 3, typed_utf8_bytes: Buffer.byteLength("42.750 kgĐã rà soát"), scripted_ms: gridMs}, invariant: "same canonical v2; leading zero IDs, decimal-comma and formula-like text remain unchanged", provenance: "one warm automated browser sample, complete raw replacement precomputed; field actions are not human productivity or provider quality"};
  await info.attach("aw08-comparison-table", {body: JSON.stringify(measurement, null, 2), contentType: "application/json"});
  console.log("AW08_COMPARISON " + JSON.stringify(measurement));
});
