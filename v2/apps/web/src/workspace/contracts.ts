export type Workspace = {id: string; name: string};
export type Message = {id: string; role: string; content: string; run_id?: string};
export type SourceFile = {id: string; filename: string; bytes: number};
export type Artifact = {id: string; title: string; filename: string; version: number; content?: string};
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
  if (!/\.(txt|md|csv)$/i.test(filename)) return "Choose a TXT, Markdown, or CSV file.";
  if (bytes > 256 * 1024) return "This file is too large. Choose a text file smaller than 256 KB.";
  return null;
}
export function safeLink(href: string): string | undefined {
  return /^(https?:\/\/|mailto:)/i.test(href) ? href : undefined;
}
