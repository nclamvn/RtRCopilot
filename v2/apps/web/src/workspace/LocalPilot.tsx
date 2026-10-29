"use client";

import {useEffect, useRef, useState} from "react";
import {api, WorkspaceApiError} from "./api";

export type LocalDiagnostics = {
  format: "agent-workspace-diagnostics-v1";
  application: {version: string; workflow_version: string; build_id: string};
  runtime: {simulation: boolean; available: boolean; reason_code: string | null};
  dependencies: Record<"pydantic-ai-slim" | "dbos" | "openai" | "mcp", string | null>;
  counts: {workspaces: number; files: number; artifacts: number; runs_active: number};
  checks: {network_tested: false; real_ai_accepted: false};
  recovery: {code: string; hint: string}[];
};

const codes: Record<string, string> = {
  model_not_configured: "No model is configured. Use explicit simulation for this local pilot.",
  private_configuration_invalid: "The private configuration needs review in your local terminal.",
  invalid_loopback_origins: "The local origin configuration needs review before restarting.",
  workspace_api_key_not_configured: "No private model key is configured. Do not paste a key into chat.",
  external_processing_not_approved: "External processing is not enabled. This pilot remains local/mock.",
  unsupported_provider: "The configured provider is not supported by this local runtime.",
  unsupported_provider_endpoint: "The configured provider endpoint is not supported.",
  provider_dependencies_not_installed: "Required provider dependencies are missing. Review the offline preflight before restarting.",
  simulation_fixture_not_installed: "The local simulation fixture is unavailable. Check the installed pilot kit.",
  runtime_unavailable: "This local runtime is unavailable. Review the offline preflight before restarting.",
};
const packageVersion = (value: unknown): value is string => typeof value === "string" && value.length <= 64 && /^[0-9][0-9A-Za-z.+-]*$/.test(value);
const sourceFingerprint = (value: unknown): value is string => typeof value === "string" && /^python-source-[a-f0-9]{20}$/.test(value);
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("The local diagnostic response is not supported. No file was downloaded.");
  return value as Record<string, unknown>;
}
/** Reconstruct declared fields, never export raw logs, response extras or configuration. */
export function diagnosticDownload(value: unknown): LocalDiagnostics {
  const root = record(value); const application = record(root.application); const runtime = record(root.runtime);
  const dependencies = record(root.dependencies); const counts = record(root.counts); const checks = record(root.checks);
  if (root.format !== "agent-workspace-diagnostics-v1" || application.version !== "0.1.0-aw07" || application.workflow_version !== "workspace-aw06-v1" || !sourceFingerprint(application.build_id)
    || typeof runtime.simulation !== "boolean" || typeof runtime.available !== "boolean" || checks.network_tested !== false || checks.real_ai_accepted !== false) {
    throw new Error("The local diagnostic response is not supported. No file was downloaded.");
  }
  const safeDependencies = {} as LocalDiagnostics["dependencies"];
  for (const name of ["pydantic-ai-slim", "dbos", "openai", "mcp"] as const) {
    const version = dependencies[name];
    if (version !== null && !packageVersion(version)) throw new Error("The local diagnostic response is not supported. No file was downloaded.");
    safeDependencies[name] = version;
  }
  const safeCounts = {} as LocalDiagnostics["counts"];
  for (const name of ["workspaces", "files", "artifacts", "runs_active"] as const) {
    const count = counts[name];
    if (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0) throw new Error("The local diagnostic response is not supported. No file was downloaded.");
    safeCounts[name] = count;
  }
  const safeCode = runtime.reason_code === null ? null : typeof runtime.reason_code === "string" && Object.hasOwn(codes, runtime.reason_code) ? runtime.reason_code : "runtime_unavailable";
  const recovery = Array.isArray(root.recovery) ? root.recovery.slice(0, 8).flatMap(item => {
    const entry = record(item); return typeof entry.code === "string" && Object.hasOwn(codes, entry.code) ? [{code: entry.code, hint: codes[entry.code]}] : [];
  }) : [];
  return {format: "agent-workspace-diagnostics-v1", application: {version: application.version, workflow_version: application.workflow_version, build_id: application.build_id},
    runtime: {simulation: runtime.simulation, available: runtime.available, reason_code: safeCode}, dependencies: safeDependencies, counts: safeCounts,
    checks: {network_tested: false, real_ai_accepted: false}, recovery};
}

export function LocalPilot() {
  const [value, setValue] = useState<LocalDiagnostics | null>(null);
  const [error, setError] = useState(""); const [notice, setNotice] = useState(""); const [busy, setBusy] = useState(false);
  const generation = useRef(0); const locked = useRef(false);
  useEffect(() => () => {generation.current++;}, []);
  async function inspect(download: boolean) {
    if (locked.current) return;
    const current = generation.current; locked.current = true; setBusy(true); setError(""); setNotice(""); setValue(null);
    try {
      const result = diagnosticDownload(await api<unknown>("/diagnostics"));
      if (current !== generation.current) return;
      setValue(result);
      if (download) {
        const blob = new Blob([JSON.stringify(result, null, 2) + "\n"], {type: "application/json"}); const url = URL.createObjectURL(blob);
        const link = document.createElement("a"); link.href = url; link.download = "agent-workspace-diagnostics.json";
        try {link.click();} finally {setTimeout(() => URL.revokeObjectURL(url), 1000);}
        setNotice("Diagnostic file downloaded locally. Nothing was uploaded or sent to a model.");
      }
    } catch (cause) {if (current === generation.current) setError(cause instanceof WorkspaceApiError ? cause.message : "Local checks are unavailable or the response is unsupported. Saved work is unchanged. No diagnostic file was downloaded.");}
    finally {locked.current = false; if (current === generation.current) setBusy(false);}
  }
  return <section className="aw-local-pilot" aria-label="Local pilot operation">
    <h3>Local pilot</h3><p className="aw-muted">Check this running instance without contacting a model. Simulation validates the software, not AI quality.</p>
    <div className="aw-control-actions"><button disabled={busy} onClick={() => void inspect(false)}>Check local runtime</button><button disabled={busy} onClick={() => void inspect(true)}>Download safe diagnostics</button></div>
    {error && <p className="aw-inline-error" role="alert">{error} Start the local runtime from your terminal, then check again. Do not delete your data directory to reconnect.</p>}
    {notice && <p className="aw-muted" role="status">{notice}</p>}
    {value && <dl className="aw-settings-facts" aria-label="Local runtime details"><div><dt>Application</dt><dd>{value.application.version}</dd></div><div><dt>Workflow</dt><dd>{value.application.workflow_version}</dd></div><div><dt>Backend source</dt><dd>{value.application.build_id}</dd></div><div><dt>Runtime</dt><dd>{value.runtime.simulation ? "Local simulation" : value.runtime.reason_code === "model_not_configured" ? "No model configured" : "Model mode, not evaluated"}{value.runtime.available ? " · Available" : " · Unavailable"}</dd></div><div><dt>Your saved work</dt><dd>{value.counts.workspaces} workspace(s), {value.counts.files} source(s), {value.counts.artifacts} output(s)</dd></div><div><dt>Active requests</dt><dd>{value.counts.runs_active}</dd></div></dl>}
    {value && <p className="aw-muted aw-diagnostic-scope">The backend source fingerprint identifies Python source, not the frontend, a compiled build or a verified release.</p>}
    {value && value.recovery.length > 0 && <ul aria-label="Local recovery guidance">{value.recovery.map((item, index) => <li key={`${item.code}-${index}`}>{item.hint}</li>)}</ul>}
    <p className="aw-muted aw-diagnostic-scope">Diagnostics contain version identifiers, dependency versions, counts for your session and known status codes only. No conversation, filenames, memory, credentials or raw logs. A private runtime backup is different: keep it private.</p>
    <details className="aw-pilot-guide"><summary>Your first local project</summary>
      <ol><li>Create a workspace for one project.</li><li>Add a small TXT, Markdown or CSV source containing synthetic data.</li><li>In simulation, send <code>fixture:create</code> for a small source, or <code>fixture:brief</code> to exercise multi-source reading. These commands copy scripted content; they do not understand the source.</li><li>Open Outputs, edit a draft and save a new version. The old version stays available.</li><li>Use Project context to select sources, save your project brief or continue from an exact output version.</li><li>Reload and return to the project. Download its content ZIP from Workspace data when you need a portable copy.</li></ol>
      <p className="aw-muted">Without a model, manual documents and tables still work. A successful fixture journey is not approval to call an external model.</p>
    </details>
    <details className="aw-pilot-recovery"><summary>Before an upgrade or recovery</summary><ol><li>Save edits first. Unsaved browser drafts are not part of a server backup.</li><li>Stop active requests and reconcile any uncertain action receipt. Then stop the local launcher.</li><li>Run the offline preflight and private backup commands in your terminal, following the pilot guide supplied with the application.</li><li>Restore only to a new data directory with a compatible application version. Keep the original directory and backup until the recovered workspace has been checked.</li></ol><p className="aw-muted">This browser cannot run shell commands, stop the server or restore a database. A content ZIP import creates a new workspace; it is not a runtime rollback.</p></details>
  </section>;
}
