export const composerKey = (workspaceId: string) => `agent-workspace:composer:${workspaceId}`;
export type ComposerDraft = {content: string; revision: number};

/** The in-memory copy survives a storage outage; callers decide whether leaving
 * an unsaved draft is safe. Only the selected workspace's key is ever touched. */
export class ComposerDrafts {
  private values = new Map<string, ComposerDraft>();
  load(workspaceId: string): {draft: ComposerDraft; stored: boolean} {
    const cached = this.values.get(workspaceId);
    if (cached) return {draft: cached, stored: this.persist(workspaceId, cached)};
    let stored = true; let draft: ComposerDraft = {content: "", revision: 0};
    try {
      const value = JSON.parse(localStorage.getItem(composerKey(workspaceId)) ?? "null");
      if (typeof value?.content === "string" && value.content.length <= 16000 && Number.isInteger(value.revision) && value.revision >= 0) draft = value;
    } catch {stored = false;}
    this.values.set(workspaceId, draft);
    return {draft, stored};
  }
  write(workspaceId: string, content: string): {draft: ComposerDraft; stored: boolean} {
    const previous = this.values.get(workspaceId) ?? this.load(workspaceId).draft;
    const draft = {content, revision: previous.revision + 1}; this.values.set(workspaceId, draft);
    return {draft, stored: this.persist(workspaceId, draft)};
  }
  revision(workspaceId: string) {return this.values.get(workspaceId)?.revision ?? 0;}
  forget(workspaceId: string) {this.values.delete(workspaceId); try {localStorage.removeItem(composerKey(workspaceId)); return true;} catch {return false;}}
  private persist(workspaceId: string, draft: ComposerDraft) {
    try {if (draft.content) localStorage.setItem(composerKey(workspaceId), JSON.stringify(draft)); else localStorage.removeItem(composerKey(workspaceId)); return true;}
    catch {
      // A blocked remove must not silently leave already-sent text behind. If
      // writes still work, an explicit empty tombstone supersedes that cache.
      if (!draft.content) {try {localStorage.setItem(composerKey(workspaceId), JSON.stringify(draft)); return true;} catch { /* Caller retains a visible clear-failure warning. */ }}
      return false;
    }
  }
}
