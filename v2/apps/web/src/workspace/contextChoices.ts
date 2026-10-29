import type {Artifact} from "./contracts";

export type ContextReference = {kind: "file" | "artifact"; id: string; version?: number};
export type ContextChoices = {references: ContextReference[]; target: ContextReference | null; review_edits?: boolean};
export const emptyContext = (): ContextChoices => ({references: [], target: null});
const key = (workspaceId: string) => `agent-workspace:context:${workspaceId}`;
export function referenceKey(reference: ContextReference): string {return `${reference.kind}:${reference.id}:${reference.version ?? ""}`;}
export function contextIdentity(value: ContextChoices): string {
  // Order affects the input inventory. Match the server's exact request identity.
  return JSON.stringify({references: value.references, target: value.target, ...(value.review_edits ? {review_edits: true} : {})});
}
function valid(value: unknown): value is ContextReference {
  if (!value || typeof value !== "object") return false;
  const item = value as ContextReference;
  return ["file", "artifact"].includes(item.kind) && typeof item.id === "string" && /^[\w-]{1,160}$/.test(item.id)
    && (item.version === undefined || Number.isSafeInteger(item.version) && item.version > 0)
    && (item.kind !== "file" || item.version === undefined);
}
/** Browser choices are convenience only. The server revalidates every reference. */
export class WorkspaceContextChoices {
  private cache = new Map<string, ContextChoices>();
  private durability = new Map<string, boolean>();
  load(workspaceId: string): ContextChoices {
    const cached = this.cache.get(workspaceId); if (cached) return cached;
    let value = emptyContext();
    try {
      const item = JSON.parse(localStorage.getItem(key(workspaceId)) ?? "null");
      if (item && Array.isArray(item.references) && item.references.length <= 20 && item.references.every(valid)
        && (item.target === null || valid(item.target) && item.target.kind === "artifact" && item.target.version !== undefined)) {
        value = {references: item.references, target: item.target, ...(item.review_edits === true && item.target ? {review_edits: true} : {})};
      }
      this.durability.set(workspaceId, true);
    } catch {this.durability.set(workspaceId, false); /* Browser storage is not authority or context content. */ }
    this.cache.set(workspaceId, value); return value;
  }
  isStored(workspaceId: string) {return this.durability.get(workspaceId) ?? false;}
  save(workspaceId: string, value: ContextChoices): boolean {
    this.cache.set(workspaceId, value);
    try {localStorage.setItem(key(workspaceId), JSON.stringify(value)); this.durability.set(workspaceId, true); return true;} catch {this.durability.set(workspaceId, false); return false;}
  }
  forget(workspaceId: string) {this.cache.delete(workspaceId); this.durability.delete(workspaceId); try {localStorage.removeItem(key(workspaceId));} catch { /* Deleted workspace remains fenced on server. */ }}
}
export function artifactReference(artifact: Artifact): ContextReference {return {kind: "artifact", id: artifact.id, version: artifact.version};}
