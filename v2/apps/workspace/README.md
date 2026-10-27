# Agent Workspace local prototype

AW-01 adds a neutral workspace next to the existing application. It does not
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

1. Create a workspace and upload a small UTF-8 TXT, Markdown or CSV file. A
   synthetic sample is available at
   `/Users/os/RtR/KnowledgeBase/RtR_Copilot/docs/agent-workspace/fixtures/harbor-notes.md`.
2. Send `fixture:create`, then `fixture:edit`.
3. Open Outputs, switch between versions 1 and 2, download and reload the page.
4. `fixture:chat` exercises text streaming; `fixture:slow` exercises reload/Stop;
   `fixture:error` exercises failure without deleting a valid existing draft.

These commands use an assistant-authored PydanticAI FunctionModel in the test
fixture package. They are **not natural-language intelligence or model-quality
evidence**. The UI identifies the simulation. Production mode never falls back
to this fixture; without model configuration it reports unavailable before
creating a run. The minimal lock does not install a provider extra. No real
provider evaluation or legacy credential reuse is included in AW-01 acceptance.

## Supported limits

- TXT/Markdown/CSV uploads: 256,000 UTF-8 bytes each, 20 files and 1,000,000 bytes
  total per workspace. An individual agent source read is limited to 64,000
  bytes; a larger source returns `file_context_limit`, never silent truncation.
- Artifacts: versioned Markdown drafts only. Previous versions are immutable;
  revisions require the current version. No Office authoring/rendering yet.
- Original run deadline, logical request/tool/token limits, physical dispatch
  reservations and cumulative output limits persist across recovery.
- Stop records a cancellation request and fences publication. A non-preemptible
  model step may take time to exit; the UI does not claim immediate worker exit.
- Closing/reloading a tab only drops the subscription. Durable event cursors and
  terminal snapshots recover the view without submitting the prompt again.
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

See `/Users/os/RtR/KnowledgeBase/RtR_Copilot/docs/agent-workspace/AW-01.md` for
the acceptance record, repairs and remaining requirements, and `proof/README.md`
for the native integration proof and raw dependency-license inventory.
