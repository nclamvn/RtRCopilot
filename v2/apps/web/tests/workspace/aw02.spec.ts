import {test, expect, type Page} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {execFileSync} from "node:child_process";
import {readFile} from "node:fs/promises";
import {resolve} from "node:path";
const python = resolve("../workspace/.venv/bin/python");
const fixtures = JSON.parse(execFileSync(python, ["-c", `import io,json,base64
from docx import Document
from openpyxl import Workbook
from reportlab.pdfgen import canvas
d=Document();d.add_paragraph('DOCX evidence: Đà Nẵng capacity 24750 units.'); b=io.BytesIO();d.save(b)
w=Workbook();w.active.append(['Location','Budget']);w.active.append(['Hà Nội',91230]);x=io.BytesIO();w.save(x)
p=io.BytesIO();c=canvas.Canvas(p);c.drawString(40,760,'PDF evidence: local sample 317 units.');c.save()
print(json.dumps({'docx':base64.b64encode(b.getvalue()).decode(),'xlsx':base64.b64encode(x.getvalue()).decode(),'pdf':base64.b64encode(p.getvalue()).decode()}))`], {encoding: "utf8"}));
async function create(page: Page, name: string) {
  await page.goto("/workspace"); await expect(page.getByRole("status").filter({hasText: "Simulation"}).first()).toBeVisible();
  await page.getByRole("button", {name: "New workspace", exact: false}).click(); await page.getByLabel("Workspace name").fill(name); await page.getByRole("button", {name: "Create workspace", exact: true}).click(); await expect(page.getByRole("heading", {name, exact: true})).toBeVisible();
  const spaces = await (await page.request.get("/api/workspace/workspaces")).json(); return spaces.items.find((item: {name: string}) => item.name === name).id as string;
}
async function send(page: Page, command: string) {
  const composer = page.getByRole("textbox", {name: "Message", exact: true}); await composer.fill(command);
  const ack = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/api/workspace/runs"));
  await composer.press("Enter"); const result = await (await ack).json();
  await expect.poll(async () => (await (await page.request.get(`/api/workspace/runs/${result.run_id}`)).json()).state).toBe("completed");
  await expect(page.getByRole("button", {name: "Send", exact: false})).toBeVisible();
}
async function download(page: Page, format: string) {
  await page.getByLabel("Export format").selectOption(format); const pending = page.waitForEvent("download"); await page.getByRole("link", {name: "Download", exact: true}).click(); const result = await pending; expect(result.suggestedFilename()).toMatch(new RegExp(`\\.${format}$`)); return readFile((await result.path())!);
}
function parseBinary(data: Buffer, format: string) {
  return execFileSync(python, ["-c", `import io,sys,base64,json
b=io.BytesIO(base64.b64decode(sys.stdin.read()))
if sys.argv[1]=='docx':
 from docx import Document
 d=Document(b);print('\\n'.join([p.text for p in d.paragraphs]+[' | '.join(c.text for c in r.cells) for t in d.tables for r in t.rows]))
elif sys.argv[1]=='xlsx':
 from openpyxl import load_workbook
 w=load_workbook(b,data_only=False);print(json.dumps(list(w.active.values),ensure_ascii=False))
elif sys.argv[1]=='pdf':
 from pypdf import PdfReader
 print('\\n'.join(p.extract_text() for p in PdfReader(b).pages))`, format], {input: data.toString("base64"), encoding: "utf8"});
}
test("REAL AW02 mixed-source batch → brief/table → exact exports and preserved manual versions", async ({page}) => {
  const workspaceId = await create(page, "Mixed format study");
  const csv = 'Site,Quantity,Note\n"Đà Nẵng",24750,"Comma, preserved"\n"Hà Nội",91230,"=1+1"\n';
  await page.getByLabel("Source file", {exact: true}).setInputFiles([
    {name: "study.md", mimeType: "text/markdown", buffer: Buffer.from("# Multi-source study\nUnique control 62019. Keep the evidence exactly.")},
    {name: "capacity.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: Buffer.from(fixtures.docx, "base64")},
    {name: "budget.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from(fixtures.xlsx, "base64")},
    {name: "count.pdf", mimeType: "application/pdf", buffer: Buffer.from(fixtures.pdf, "base64")},
    {name: "sites.csv", mimeType: "text/csv", buffer: Buffer.from(csv)},
    {name: "broken.pdf", mimeType: "application/pdf", buffer: Buffer.from("broken document")},
    {name: "unsupported.exe", mimeType: "application/octet-stream", buffer: Buffer.from("not allowed")},
  ]);
  await expect(page.getByLabel("Upload results")).toContainText("Not saved:"); await expect(page.getByLabel("Upload results").getByText("Saved", {exact: true})).toHaveCount(5);
  const files = await (await page.request.get(`/api/workspace/workspaces/${workspaceId}/files`)).json(); expect(files.items).toHaveLength(5);
  await page.getByRole("button", {name: "capacity.docx", exact: false}).click(); await expect(page.getByLabel("Source preview")).toContainText("Đà Nẵng capacity 24750");
  const original = page.waitForEvent("download"); await page.getByRole("link", {name: "Download original"}).click(); expect(await readFile((await (await original).path())!)).toEqual(Buffer.from(fixtures.docx, "base64"));
  await send(page, "fixture:brief"); await expect(page.getByLabel("Artifact preview")).toBeVisible();
  const outputs = await (await page.request.get(`/api/workspace/workspaces/${workspaceId}/artifacts`)).json(); const document = outputs.items.find((item: {kind: string}) => item.kind === "document");
  const first = await (await page.request.get(`/api/workspace/artifacts/${document.id}?version=1`)).json();
  for (const token of ["62019", "24750", "91230", "317"]) expect(first.content).toContain(token);
  expect((await download(page, "md")).toString("utf8")).toBe(first.content);
  for (const format of ["docx", "pdf"]) {const parsed = parseBinary(await download(page, format), format); for (const token of ["62019", "24750", "91230", "317"]) expect(parsed).toContain(token);}
  await page.getByRole("tab", {name: "Edit", exact: true}).click(); const editor = page.getByLabel("Edit Markdown text"); const changed = first.content.replace("62019", "62020"); await editor.fill(changed);
  let revisionRequests = 0; page.on("request", request => {if (request.method() === "POST" && request.url().endsWith("/revisions")) revisionRequests++;});
  await page.getByRole("button", {name: "Save new version"}).dblclick(); await expect(page.getByLabel("Artifact version")).toHaveValue("2"); expect(revisionRequests).toBe(1);
  const second = await (await page.request.get(`/api/workspace/artifacts/${document.id}`)).json(); expect(second.content).toBe(changed);
  expect((await (await page.request.get(`/api/workspace/artifacts/${document.id}?version=1`)).json()).content).toBe(first.content);
  await page.getByRole("tab", {name: "Changes", exact: true}).click(); await expect(page.locator(".aw-diff")).toContainText("62020"); await expect(page.locator(".aw-diff")).toContainText("62019");
  await page.reload(); await page.getByRole("button", {name: "Outputs", exact: false}).click(); await page.locator(".aw-output-list button").first().click(); await expect(page.getByLabel("Artifact version")).toHaveValue("2"); await page.getByRole("tab", {name: "Edit", exact: true}).click(); await expect(page.getByLabel("Edit Markdown text")).toHaveValue(changed);
  await page.screenshot({path: "test-results/workspace/aw02-desktop-editing.png"});
  await send(page, "fixture:patch"); await expect(page.getByLabel("Artifact version")).toHaveValue("3");
  const patched = await (await page.request.get(`/api/workspace/artifacts/${document.id}`)).json(); expect(patched.content).toBe(changed.replace("Fixture copy-through, not AI synthesis.", "Fixture localized revision, not AI analysis."));
  await send(page, "fixture:table"); await expect(page.locator(".aw-artifact-content table")).toBeVisible(); await expect(page.locator(".aw-artifact-content table")).toContainText("Comma, preserved");
  const updated = await (await page.request.get(`/api/workspace/workspaces/${workspaceId}/artifacts`)).json(); const table = updated.items.find((item: {kind: string}) => item.kind === "table"); const canonical = await (await page.request.get(`/api/workspace/artifacts/${table.id}`)).json();
  expect(canonical.content).toContain("=1+1"); expect((await download(page, "csv")).toString("utf8")).toContain("'=1+1"); const parsed = parseBinary(await download(page, "xlsx"), "xlsx"); expect(parsed).toContain("=1+1"); expect(parsed).toContain("Comma, preserved"); expect(parsed).toContain("24750");
  await page.screenshot({path: "test-results/workspace/aw02-desktop-table.png"});
});

test("REAL AW02 source paging, local research snapshots, scoped IDs and blocked URL inputs", async ({page, browser}) => {
  const workspaceId = await create(page, "Local research study");
  await page.getByLabel("Source file", {exact: true}).setInputFiles({name: "long.txt", mimeType: "text/plain", buffer: Buffer.from("start " + "bounded text ".repeat(1600) + "final-tail")}); await expect(page.getByLabel("Upload results")).toContainText("Saved");
  await page.getByRole("button", {name: "long.txt", exact: false}).click(); await expect(page.getByLabel("Source preview")).toContainText("start"); await page.getByRole("button", {name: "Next page"}).click(); await expect(page.getByLabel("Source preview")).toContainText("final-tail");
  await page.getByRole("button", {name: "Search local fixtures"}).click(); await page.getByLabel("Search local fixture sources").fill("harbor"); await page.getByRole("button", {name: "Search fixtures", exact: true}).click(); await expect(page.locator(".aw-research-results li").first()).toBeVisible();
  await expect(page.getByLabel("Local research")).toContainText("No live web search"); await page.locator(".aw-research-results li").first().getByRole("button", {name: "Read snapshot"}).click(); await expect(page.locator(".aw-research-results .aw-source-text")).toBeVisible();
  await page.locator(".aw-research-results li").first().getByRole("button", {name: "Import snapshot"}).click(); await expect(page.getByLabel("Source preview")).toBeVisible(); await page.getByText("Source provenance", {exact: true}).click(); await expect(page.getByLabel("Source preview")).toContainText("offline_fixture");
  const sources = await (await page.request.get(`/api/workspace/workspaces/${workspaceId}/files`)).json(); const imported = sources.items.find((item: {provenance?: {provenance?: string}}) => item.provenance?.provenance === "offline_fixture"); expect(imported).toBeTruthy();
  const origin = new URL(page.url()).origin; const outsider = await browser.newContext({baseURL: origin, extraHTTPHeaders: {origin}}); expect((await outsider.request.post("/api/workspace/session", {data: {}})).ok()).toBe(true); expect((await outsider.request.get(`/api/workspace/files/${imported.id}`)).status()).toBe(404); expect((await outsider.request.get(`/api/workspace/files/${imported.id}/download`)).status()).toBe(404); await outsider.close();
  const blocked = await page.request.post(`/api/workspace/workspaces/${workspaceId}/research/read`, {data: {source_id: "http://169.254.169.254/latest/meta-data"}}); expect(blocked.status()).toBe(404);
  const unknown = await page.request.post(`/api/workspace/workspaces/${workspaceId}/research/search`, {data: {query: "https://127.0.0.1/private"}}); expect((await unknown.json()).results).toEqual([]);
  await page.setViewportSize({width: 390, height: 844}); await page.screenshot({path: "test-results/workspace/aw02-mobile-source.png"}); expect((await new AxeBuilder({page}).include(".agent-workspace").analyze()).violations).toEqual([]);
  await page.getByRole("button", {name: "Close outputs"}).click(); await send(page, "fixture:research"); await expect(page.getByLabel("Artifact preview")).toBeVisible(); await expect(page.locator(".aw-artifact-content")).toContainText("120000"); await expect(page.locator(".aw-artifact-content")).toContainText("135000"); await expect(page.locator(".aw-artifact-content")).toContainText("https://harbor-public.test/planning-2026");
});

test("REAL AW02 unsaved draft survives switch/reload, stale save conflict and renderer failure", async ({page}) => {
  const workspaceId = await create(page, "Draft safety study"); await page.getByLabel("Source file", {exact: true}).setInputFiles({name: "safety.md", mimeType: "text/markdown", buffer: Buffer.from("# Safety\nKeep 4512 intact.")}); await expect(page.getByLabel("Upload results")).toContainText("Saved"); await send(page, "fixture:brief"); await expect(page.getByLabel("Artifact preview")).toBeVisible();
  const outputs = await (await page.request.get(`/api/workspace/workspaces/${workspaceId}/artifacts`)).json(); const artifact = outputs.items[0]; const current = await (await page.request.get(`/api/workspace/artifacts/${artifact.id}`)).json();
  await page.getByRole("tab", {name: "Edit", exact: true}).click(); const draft = current.content + "\n\nUnsaved localized work."; await page.getByLabel("Edit Markdown text").fill(draft); await page.getByRole("button", {name: "Close outputs"}).click(); await page.getByRole("button", {name: "Outputs", exact: false}).click(); await page.getByRole("tab", {name: "Edit", exact: true}).click(); await expect(page.getByLabel("Edit Markdown text")).toHaveValue(draft);
  page.once("dialog", dialog => dialog.accept()); await page.reload(); await page.getByRole("button", {name: "Outputs", exact: false}).click(); await page.locator(".aw-output-list button").first().click(); await page.getByRole("tab", {name: "Edit", exact: true}).click(); await expect(page.getByLabel("Edit Markdown text")).toHaveValue(draft);
  const external = await page.request.post(`/api/workspace/artifacts/${artifact.id}/revisions`, {data: {expected_version: 1, content: current.content + "\nOther local edit.", request_id: crypto.randomUUID()}}); expect(external.status()).toBe(200);
  await page.getByRole("button", {name: "Save new version"}).click(); await expect(page.locator(".aw-inline-error")).toContainText("newer version"); await expect(page.getByLabel("Edit Markdown text")).toHaveValue(draft);
  // Narrow UI transport fault injection: forward the export to the real API
  // with an unsupported target, then relay its actual 422. No happy-path API mock.
  await page.route(`**/api/workspace/artifacts/${artifact.id}/download?**`, async route => {const url = new URL(route.request().url()); url.searchParams.set("format", "xlsx"); const response = await route.fetch({url: url.toString()}); expect(response.status()).toBe(422); await route.fulfill({response});});
  await page.getByLabel("Export format").selectOption("pdf"); await page.getByRole("link", {name: "Download", exact: true}).click(); await expect(page.locator(".aw-inline-error")).toContainText("Export failed"); await expect(page.getByLabel("Edit Markdown text")).toHaveValue(draft);
  const versions = await (await page.request.get(`/api/workspace/artifacts/${artifact.id}/versions`)).json(); expect(versions.items).toHaveLength(2);
  await page.getByRole("button", {name: "Close outputs"}).click(); await page.getByRole("button", {name: "Outputs", exact: false}).click(); await page.locator(".aw-output-list button").first().click(); await page.getByLabel("Artifact version").selectOption("1"); await page.getByRole("tab", {name: "Edit", exact: true}).click(); await expect(page.getByRole("button", {name: "Save new version"})).toBeDisabled();
});

test("REAL AW02 manual authoring needs no model: create document/table → revise → parsed exports", async ({page}) => {
  const workspaceId = await create(page, "Manual authoring study"); let dispatches = 0; page.on("request", request => {if (request.method() === "POST" && request.url().endsWith("/api/workspace/runs")) dispatches++;});
  await page.getByRole("button", {name: "Outputs", exact: false}).click(); await page.getByRole("button", {name: "New document", exact: false}).click(); await expect(page.getByRole("button", {name: "Save first version"})).toBeDisabled();
  await page.getByLabel("Title", {exact: true}).fill("Editable field note"); const original = "# Field note\n\n## Preserve\nĐà Nẵng 24,750 units.\n\n## Revise\nInitial local detail."; await page.getByLabel("Markdown content", {exact: true}).fill(original); await page.getByRole("button", {name: "Save first version"}).click(); await expect(page.getByLabel("Artifact version")).toHaveValue("1");
  await page.getByRole("tab", {name: "Edit", exact: true}).click(); const updated = original.replace("Initial local detail.", "Reviewed local detail."); await page.getByLabel("Edit Markdown text").fill(updated); await page.getByRole("button", {name: "Save new version"}).click(); await expect(page.getByLabel("Artifact version")).toHaveValue("2"); expect((await download(page, "md")).toString("utf8")).toBe(updated); expect(parseBinary(await download(page, "docx"), "docx")).toContain("Đà Nẵng 24,750 units."); expect(parseBinary(await download(page, "pdf"), "pdf")).toContain("Reviewed local detail.");
  await page.getByRole("button", {name: "New table", exact: false}).click(); await page.getByLabel("Title", {exact: true}).fill("Input ledger"); await page.getByLabel("CSV content", {exact: true}).fill('Item,Amount\n"Unicode Việt Nam",62019\n'); await page.getByRole("button", {name: "Save first version"}).click(); await expect(page.locator(".aw-artifact-content table")).toContainText("Unicode Việt Nam"); expect(parseBinary(await download(page, "xlsx"), "xlsx")).toContain("62019"); expect(dispatches).toBe(0);
  const history = await (await page.request.get(`/api/workspace/workspaces/${workspaceId}/messages`)).json(); expect(history.items).toEqual([]);
});
