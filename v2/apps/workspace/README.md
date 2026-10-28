# Agent Workspace local prototype

AW-01 through AW-04 add a neutral workspace next to the existing application. It does not
activate the legacy executor, import the RtR answer pipeline or discover its
credentials. Current acceptance is **local/mock integration only**, as requested
by the user. It is not an accepted production AI assistant.

## Run locally (one command, no legacy services)

Use Python 3.12. The isolated environment and dependency lock belong to this
directory; do not upgrade the legacy backend environment.

```sh
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/workspace
uv sync --frozen --no-cache
.venv/bin/workspace launch --simulation
```

This starts the API on 8110 and the enabled UI on 3110, both bound to loopback.
It uses the existing Next `.next` output, no copied project or per-task build.
Stop with Ctrl+C; the launcher cleans up only its own child process groups.
Do not launch a second copy on occupied ports. For an already running UI/API,
stop the existing operator-owned processes before using this launcher.

For separate terminal control, run:

```sh
WORKSPACE_TEST_MODE=1 PYDANTIC_AI_NO_BANNER=1 \
  .venv/bin/python -m uvicorn agent_workspace.api:app --host 127.0.0.1 --port 8110
# Another terminal:
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
creating a run. The lock includes the explicit provider SDK; no real
provider evaluation or legacy credential reuse is included in this acceptance.

## AW-04: private provider setup and offline doctor

The pinned official OpenAI SDK is installed by this app's lock. Model calls use
the Responses API (Sol tool calling requires Responses), `store=false`, low
reasoning effort and a maximum of 2,048 total output tokens including reasoning.
SDK and agent retries are disabled. Only the application's scoped function tools
are registered: no provider-hosted web, file search, shell or MCP is enabled.

Real external processing needs the user's endpoint/model/data/budget authority
before testing. An offline doctor or successful configuration is **not** proof
of model access or accepted AI quality. No connectivity or model-listing call is
made by configuration, doctor, readiness or startup.

When separately authorized, enter your Workspace-only key in a trusted terminal:

```sh
.venv/bin/workspace configure --config .workspace-data/provider.json \
  --allow-external-processing --model gpt-6.1-sol
WORKSPACE_CONFIG=.workspace-data/provider.json .venv/bin/workspace doctor
.venv/bin/workspace launch --config .workspace-data/provider.json
```

`configure` prompts with hidden `getpass` input and refuses echoed-stdin fallback.
It writes an atomic private `0600` profile. Do not pass a key in a command, chat,
browser, screenshot, source file or shell history. Loading a profile is explicit
through `--config`/`WORKSPACE_CONFIG`; there is no legacy/OpenAI environment-key
discovery. Symlink, unowned or permissive profile files are rejected. Keep the
profile under ignored `.workspace-data`, not in a tracked or shared directory.

The configured endpoint is restricted to `https://api.openai.com/v1`. The browser
receives sanitized readiness, never the key or private file path. The launcher
passes configuration only to the server and constructs a separate minimal UI
environment. The UI still runs inside the shared existing web checkout; Next may
load that checkout's existing environment files. The launcher does not scan/read
their secrets or claim this is an independently distributed, isolated web bundle.
`/api/workspace/readiness` and `workspace doctor` are read-only and
offline. Missing key/opt-in/unsupported endpoint is reported without raw errors.

Settings are frozen for a process. To change profile/model/tool topology: stop or
cancel active tasks, reconcile unknown effects, drain and restart. AW-04 uses
`workspace-aw04-v1`; prior active workflow versions fail closed as incompatible,
not replayed into a changed topology. Existing saved outputs remain available.
Do not run old and new API workers against one catalogue during migration.

`--fixture-tools` during configure separately permits the fixed local synthetic
research/MCP ports with a real model; each workspace still needs its own grant
and per-effect approval. This does not grant live web or an external connector.
Manual schedules remain simulation-only. The evaluation campaign uses a separate
persistent, explicitly bound shared budget; the normal UI has no entitlement to
spend that campaign's dollars. See the AW-04 evaluation instructions for scope.

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
- AW-03 adds explicit workspace memory, a fixed local MCP fixture and manual
  schedule simulation; see the following section. This is not a real connector
  or provider acceptance.
- No shell, host filesystem tools, external MCP/effects, skills, live scheduler,
  workspace sharing or production SSO is exposed in this milestone.
- Long-term list pagination, ACL revocation and production
  deployment are not complete. Session mode is per-browser local ownership, not
  organizational identity or a multi-tenant SaaS authentication system.

## AW-03: memory, local MCP and manual schedules

Use the Memory, Connections and Schedules controls in the workspace sidebar.
These panels share the existing related-information rail, not a new dashboard.

- **Memory:** explicitly save up to 100 user-authored notes (4,000 characters
  each, 64 KB total). Edit/delete use expected revisions. A memory mutation
  invalidates reusable conversation history and stops active consumers so old
  checkpoints cannot feed the old memory into a later model call. Existing
  visible chat, generated artifacts, DBOS audit history and backups are separate
  retained records. This is not forensic erasure or provider unlearning.
  `fixture:memory` exercises the current live read; no model auto-writes memory.
- **Connections:** grant the fixed local fixture permission once. `fixture:mcp-read`
  reads through an actual MCP stdio transport without repeated approval.
  `fixture:mcp-effect` proposes a synthetic outbox note, then waits for the
  server-created preview's Approve/Reject decision on the same logical run.
  No actual recipient, account or external service is connected. The executable,
  tool schema and minimal environment are fixed, not supplied by a user/document.
- **Receipts:** an effect intent is saved before dispatch. A lost response or
  crash without a confirmed receipt is shown as uncertain. Reconcile performs
  receipt lookup only; it never resends the effect. An absent receipt does not
  certify failure. Completed effects remain visible even after run cancellation.
- **Permission changes:** revocation/changed tool arguments or artifact versions
  invalidate approval. Approval lasts at most 90 seconds and never extends a
  run's persisted deadline. Approval flags in chat/history or client payloads
  are not authority. Revocation/rejection/forget/cancel remain possible after
  normal command quota exhaustion, within bounded cleanup allowances.
- **Schedules:** at most 100 once-only prompts per workspace. The manual clock
  starts at 0 simulation seconds, moves only forward and is bounded to one
  simulation year. Create, pause, resume, cancel and explicitly advance it.
  A repeated/concurrent tick cannot create duplicate logical runs. Busy jobs
  stay pending for another explicit tick. There is no background timer or cron.
  Scheduled effects still require the same current per-action approval.
- **Resource limits:** one active run per workspace, eight globally. Two short
  model-I/O slots and two short MCP-I/O slots bound resource use; time waiting
  for approval holds neither. Full capacity returns an explicit error instead
  of an invisible unbounded queue. DBOS is still the sole recovery owner.

The MCP SDK is pinned in this app's lockfile, not the legacy backend. Only the
fixed Python fixture runs as a subprocess; no shell/code/browser executor is
enabled and Python socket guards are not an OS sandbox claim. A pre-migration
backup of the local AW-02 catalogue is retained privately under `.workspace-data/`.

## Own your workspace data

The workspace data panel exports one transactionally consistent ZIP with original
source bytes, extracted text/metadata, every saved artifact version, visible chat,
explicit current memory, schedules and a SHA-256 manifest. Paths use opaque IDs,
not user filenames. Export is bounded to 20 MiB uncompressed content and 2,500 ZIP
members; an oversized snapshot fails explicitly rather than silently omitting data.
No session hashes, provider configuration, reusable model history or DBOS journal
is included. ZIP export is a portable archive, not a full runtime backup/import.

Deletion first creates a five-minute server preview bound to workspace ID and
current resource versions. Type the exact workspace name to confirm. Changed
content invalidates the preview, and duplicate lost-ACK requests return the same
deletion receipt without repeating work. Busy tasks and unsettled effect intents
block deletion. Stop/drain tasks and reconcile uncertain effects first; a missing
fixture receipt is still unknown, not proof that an effect did not happen.

Deletion atomically tombstones identity and purges application files, artifact
versions, messages, memory, schedules, histories and content-bearing receipts.
Read routes, tools and recovery callbacks cannot revive or access a deleted ID.
Other workspaces are unchanged. **This is not forensic erasure:** DBOS audit
history, private backups, previously downloaded copies, synthetic MCP outbox
receipts and any provider retention are separate retained records. A previously
generated/downloaded file cannot be revoked by deleting its workspace.

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

See `/Users/os/RtR/KnowledgeBase/RtR_Copilot/docs/agent-workspace/AW-04.md` for
the current milestone record, AW-03.md, AW-02.md and AW-01.md for preserved baselines. Real-model
quality and live-web acceptance remain open. See `proof/README.md`
for the native integration proof and raw dependency-license inventory.
