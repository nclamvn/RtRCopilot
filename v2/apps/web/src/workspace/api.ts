export const apiRoot = "/api/workspace";
export class WorkspaceApiError extends Error {
  constructor(public code: string, public status: number) {
    const hints: Record<string, string> = {
      model_unavailable: "No model is available. Configure a permitted model or restart in explicit simulation mode.",
      workspace_service_unavailable: "The workspace service is not reachable. Start the local service, then reconnect.",
      workspace_busy: "This workspace already has a run in progress. Reconnect to it before sending another message.",
      workspace_unsettled_effects: "An action outcome is not yet confirmed. Reconcile its receipt before deleting this workspace; do not send it again.",
      delete_confirmation_stale: "Saved data changed after this preview. Keep your workspace and review deletion again before confirming.",
      delete_confirmation_mismatch: "The workspace name did not match. Nothing was deleted.",
      workspace_not_found: "This workspace is no longer available. Reconnect to refresh your workspace list.",
      workspace_archived: "This workspace is archived. Restore it to active projects before starting a new request.",
      stale_workspace_revision: "This workspace changed elsewhere. Reconnect to get its current name and archive state before trying again.",
      import_confirmation_stale: "This import preview expired or no longer matches the snapshot and choices. Preview it again before importing.",
      invalid_workspace_archive: "This file is not a valid supported Workspace snapshot. Nothing was imported.",
      workspace_import_limit: "The snapshot exceeds the supported import limits. Nothing was imported.",
      provider_unauthorized: "The provider rejected its server-side credentials. Check the local model configuration; do not paste keys into chat.",
      provider_rate_limit: "The provider is temporarily limiting requests. Saved work is unchanged. Check provider quota before starting a new run.",
      artifact_version_conflict: "A newer version exists. Your unsaved draft is kept. Open the current version to compare before saving again.",
      version_conflict: "A newer version exists. Your unsaved draft is kept. Open the current version to compare before saving again.",
      stale_artifact_version: "A newer version exists. Your unsaved draft is kept. Open the current version to compare before saving again.",
      stale_memory_version: "This memory changed elsewhere. Your edit is kept. Review the current note before saving again.",
      stale_brief_revision: "The project brief changed elsewhere. Your edits are kept. Load the current brief before saving again.",
      context_reference_limit: "Too many references were selected. Remove some references and preview again.",
      context_selection_limit: "Too many references were selected. Remove some references and preview again.",
      context_reference_not_found: "A selected source or output version is unavailable in this workspace. Review your context choices; nothing was substituted silently.",
      context_reference_not_selected: "This source was not included in the saved request context. Select it explicitly for a new request.",
      conflicting_context_versions: "Two different versions of the same output were selected. Keep one version and preview again.",
      context_scope_changed: "The project brief or memory changed while this request was running. Saved outputs are kept. Review the new context before starting another request.",
      context_read_limit: "The request reached its source-reading limit. Keep the saved work and continue with a narrower selection.",
      context_selection_too_large: "The selected context exceeds the request limit. Choose fewer references or a smaller source region.",
      context_not_ready: "The run has not saved its context yet. Reconnect and inspect it again after the request starts.",
      context_not_found: "No context snapshot is available for this older run. Saved messages and outputs are unchanged.",
      source_replacement_conflict: "This source already has a different replacement. Review the existing link before recording another.",
      memory_version_conflict: "This memory changed elsewhere. Your edit is kept. Review the current note before saving again.",
      stale_schedule_version: "This task changed elsewhere. Refresh its current state before changing it again.",
      approval_expired: "This approval has expired. The action was not authorized. Review a new request if one is created.",
      approval_invalidated: "Permission or the saved content changed. This approval can no longer authorize the action.",
      connection_revoked: "Fixture permission was revoked. Grant permission again before preparing another test.",
      connection_disabled: "Grant this workspace permission to use the local fixture first.",
      clock_cannot_rewind: "The simulation clock cannot move backwards. Enter the current second or a later one.",
    };
    super(hints[code] ?? "The request could not finish. Saved work and unsaved edits are unchanged. Reconnect to check its state before trying again.");
  }
}
export async function checkedResponse(response: Response): Promise<Response> {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new WorkspaceApiError(typeof payload.detail === "string" ? payload.detail : payload.error?.code ?? `http_${response.status}`, response.status);
  }
  return response;
}
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiRoot}${path}`, {method: body === undefined ? "GET" : "POST", cache: "no-store", headers: body === undefined ? {} : {"content-type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  return (await checkedResponse(response)).json();
}
