# Agent Workspace local prototype

AW-01/AW-02 add a neutral workspace next to the existing application. It does not
activate the legacy executor, import the RtR answer pipeline or discover its
credentials. Current acceptance is **local/mock integration only**, as requested
by the user. It is not an accepted production AI assistant.

## Run locally

Use Python 3.12. The isolated environment and dependency lock belong to this
directory; do not upgrade the legacy backend environment.

```sh
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/workspace
uv sync --frozen --no-cache
WORKSPACE_TEST_MODE=1 PYDANTIC_AI_NO_BANNER=1 PYTHONPATH=src \
  .venv/bin/python -m uvicorn agent_workspace.api:app --host 127.0.0.1 --port 8110
```

In another terminal:

```sh
pnpm --dir /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/web dev:workspace
```

Open <http://127.0.0.1:3110/workspace>. The dedicated frontend launcher explicitly
enables the feature and binds loopback. Both page and BFF are disabled by default.
Do not expose this local session mode through a LAN/public bind or reverse proxy.
Incoming Host/Origin checks do not prove a spoofed non-browser peer is local;
loopback binding of **both** servers is part of the supported contract.

No Docker or PostgreSQL service is needed for this development prototype. DBOS
and the product catalogue use separate local SQLite databases under
`.workspace-data/`. This directory contains session hashes, files, conversation
history and artifacts. Keep it private and retain it to preserve local work.
SQLite here is development/test storage, not a production scale claim.

## Try the scripted integration flow

1. Create a workspace and upload TXT, Markdown, CSV, or supported DOCX/XLSX/text
   PDF sources, with per-file results for a mixed batch. A
   synthetic sample is available at
   `/Users/os/RtR/KnowledgeBase/RtR_Copilot/docs/agent-workspace/fixtures/harbor-notes.md`.
2. Send `fixture:brief` for multiple source texts, `fixture:table` for a CSV
   source, or `fixture:create`, then `fixture:patch` for an exact localized edit.
3. Open Outputs. Preview, edit locally, compare versions and download the selected
   version. **New document/New table also work without a model or a chat run.**
   Reload preserves saved versions and local unsaved drafts; a stale edit cannot
   overwrite another version. CSV/XLSX safety warnings describe export-only changes.
4. `fixture:chat` exercises text streaming; `fixture:slow` exercises reload/Stop;
   `fixture:error` exercises failure without deleting a valid existing draft.

5. **Search local fixtures** searches an explicitly synthetic snapshot collection.
   Read/import a result, then `fixture:research` exercises the attributed research
   path. No live search, website fetch or arbitrary URL is enabled.

These commands use an assistant-authored PydanticAI FunctionModel in the test
fixture package. They are **not natural-language intelligence or model-quality
evidence**. The UI identifies the simulation. Production mode never falls back
to this fixture; without model configuration it reports unavailable before
creating a run. The minimal lock does not install a provider extra. No real
provider evaluation or legacy credential reuse is included in this acceptance.

## Supported limits

- Source uploads: 256,000 raw bytes each, 10 files per batch, 20 files and
  1,000,000 raw bytes per workspace. Paginated text preview/agent reads preserve
  the tail of a larger supported source. Original download is byte-exact.
- Documents use canonical Markdown and export MD/DOCX/PDF. Tables use canonical
  rectangular CSV and export CSV/XLSX. Existing versions are immutable; saves
  require the current version and an idempotent request ID. Editing is locked
  while a save is pending; an old acknowledgement cannot clear a newer draft.
- Supported projections and exports are deliberately bounded, not full Office
  fidelity: see [FORMATS.md](FORMATS.md) for Unicode, layout, formulas, unsupported
  content and worker resource limits. Scans/OCR, complex Markdown/Office objects
  and spreadsheet formula calculation are not implemented.
- Original run deadline, logical request/tool/token limits, physical dispatch
  reservations and cumulative output limits persist across recovery.
- Stop records a cancellation request and fences publication. A non-preemptible
  model step may take time to exit; the UI does not claim immediate worker exit.
- Closing/reloading a tab only drops the subscription. Durable event cursors and
  terminal snapshots recover the view without submitting the prompt again.
- Fixture research is offline and marked synthetic, with URL/time/hash lineage.
  It is not a live research capability or evidence of real-model synthesis.
- No shell, host filesystem, external MCP/effects, skills, memory, approval-pause
  workflow, workspace sharing or production SSO is exposed in this milestone.
- Long-term list pagination, data export/delete UX, ACL revocation and production
  deployment are not complete. Session mode is per-browser local ownership, not
  organizational identity or a multi-tenant SaaS authentication system.

## Verify

```sh
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/workspace
PYTHONPATH=src PYDANTIC_AI_NO_BANNER=1 .venv/bin/python -m pytest tests -q
```

With both local servers running in simulation mode:

```sh
pnpm --dir /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/web exec playwright test \
  --config playwright.workspace.config.ts
```

The harness tests use real SQLite, subprocess death/restart and DBOS, with
provider sockets denied. Browser tests use the real local product API and
scripted model, except one explicitly labelled UI-only unavailable-state fixture.
The lost-ACK case injects a browser transport fault after the real API dispatch.
Do not add overlapping test runs together or equate passing these cases with
real-model usefulness.

See `/Users/os/RtR/KnowledgeBase/RtR_Copilot/docs/agent-workspace/AW-02.md` for
the latest local/mock record and AW-01.md for the preserved baseline. Real-model
quality and live-web acceptance remain open. See `proof/README.md`
for the native integration proof and raw dependency-license inventory.
