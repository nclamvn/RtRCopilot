export const apiRoot = "/api/workspace";
export class WorkspaceApiError extends Error {
  constructor(public code: string, public status: number) {
    const hints: Record<string, string> = {
      model_unavailable: "No model is available. Configure a permitted model or restart in explicit simulation mode.",
      workspace_service_unavailable: "The workspace service is not reachable. Start the local service, then reconnect.",
      workspace_busy: "This workspace already has a run in progress. Reconnect to it before sending another message.",
      artifact_version_conflict: "A newer version exists. Your unsaved draft is kept. Open the current version to compare before saving again.",
      version_conflict: "A newer version exists. Your unsaved draft is kept. Open the current version to compare before saving again.",
      stale_artifact_version: "A newer version exists. Your unsaved draft is kept. Open the current version to compare before saving again.",
      stale_memory_version: "This memory changed elsewhere. Your edit is kept. Review the current note before saving again.",
      memory_version_conflict: "This memory changed elsewhere. Your edit is kept. Review the current note before saving again.",
      stale_schedule_version: "This task changed elsewhere. Refresh its current state before changing it again.",
      approval_expired: "This approval has expired. The action was not authorized. Review a new request if one is created.",
      approval_invalidated: "Permission or the saved content changed. This approval can no longer authorize the action.",
      connection_revoked: "Fixture permission was revoked. Grant permission again before preparing another test.",
      connection_disabled: "Grant this workspace permission to use the local fixture first.",
      clock_cannot_rewind: "The simulation clock cannot move backwards. Enter the current second or a later one.",
    };
    super(hints[code] ?? `The request could not finish (${code}). Saved work and unsaved edits are unchanged.`);
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
