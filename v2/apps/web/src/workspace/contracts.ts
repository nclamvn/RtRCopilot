export type Workspace = {id: string; name: string; archived?: boolean; revision?: number; created_at?: number};
export type Message = {id: string; role: string; content: string; run_id?: string};
export type SourceFile = {id: string; filename: string; bytes: number; media_type?: string; sha256?: string; warnings?: string[]; provenance?: Record<string, unknown>};
export type SourcePage = SourceFile & {content: string; offset: number; next_offset: number | null; has_more: boolean; total_characters: number};
export type Artifact = {id: string; title: string; filename: string; version: number; content?: string; kind?: "document" | "table"};
export type ArtifactVersion = {version: number; created_at: number; characters: number; run_id: string | null};
export type ResearchSource = {id: string; title: string; url: string; snippet: string; as_of: string; provenance: "offline_fixture"};
export type Availability = {available: boolean; test_mode: boolean; model: string | null; reason: string | null; recovery: string};
export type Run = {id: string; state: string; cancel_requested: boolean; error?: string | null; usage?: {requests: number; input_tokens: number; output_tokens: number; cost_usd: number | null}};
export type WorkspaceEvent = {run_id: string; seq: number; type: string; data: Record<string, unknown>};
export type LiveState = {cursor: number; content: string; state: string; activities: string[]};
export const terminal = (state: string) => ["completed", "failed", "cancelled", "interrupted"].includes(state);
export function applyEvent(previous: LiveState, event: WorkspaceEvent): LiveState {
  if (!Number.isInteger(event.seq) || event.seq <= previous.cursor) return previous;
  const next = {...previous, cursor: event.seq};
  if (event.type === "message.delta") next.content += String(event.data.text ?? "");
  if (event.type === "message.final") next.content = String(event.data.content ?? "");
  if (event.type === "run.state") next.state = String(event.data.state ?? previous.state);
  if (event.type === "run.error") next.activities = [...next.activities, `Run failed: ${String(event.data.code ?? "unknown error")}`];
  if (event.type === "tool.start" || event.type === "tool.result") {
    next.activities = [...next.activities, `${event.type === "tool.start" ? "Working" : "Finished"}: ${String(event.data.name ?? "tool")}`];
  }
  return next;
}
export function uploadError(filename: string, bytes: number): string | null {
  if (!/\.(txt|md|csv|docx|xlsx|pdf)$/i.test(filename)) return "Choose a TXT, Markdown, CSV, DOCX, XLSX, or text PDF file.";
  if (bytes > 256000) return "This file is too large. Choose a file no larger than 256,000 bytes.";
  return null;
}

/** RFC 4180-style quoted fields; never interpret spreadsheet formulas or HTML. */
export function parseCsv(content: string): string[][] {
  const rows: string[][] = []; let row: string[] = []; let field = ""; let quoted = false;
  for (let i = 0; i < content.length; i++) {
    const char = content[i];
    if (char === '"') {if (quoted && content[i + 1] === '"') {field += '"'; i++;} else quoted = !quoted;}
    else if (char === "," && !quoted) {row.push(field); field = "";}
    else if ((char === "\n" || char === "\r") && !quoted) {if (char === "\r" && content[i + 1] === "\n") i++; row.push(field); rows.push(row); row = []; field = "";}
    else field += char;
  }
  if (field || row.length) {row.push(field); rows.push(row);}
  return rows;
}
export function safeLink(href: string): string | undefined {
  return /^(https?:\/\/|mailto:)/i.test(href) ? href : undefined;
}
