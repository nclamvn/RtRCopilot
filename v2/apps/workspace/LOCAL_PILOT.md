# Local pilot operator guide (AW-08)

This is an independent, loopback-only **source pilot kit**, not a self-contained
binary. Local/mock has a packaged FunctionModel and public/synthetic research
fixture. Real AI, web research and live connectors are **not accepted**. No
command below downloads dependencies, calls a provider, enables the legacy
executor, deploys or starts a background scheduler.

## Prerequisites and source kit

Use an already trusted Python 3.12 environment matching `uv.lock` and Node 22/24
with the pinned Next 16.2.11, React/ReactDOM 19.2.3 dependencies. Python packages,
Node dependencies and build outputs are intentionally not shipped. Clean-machine
installation and cross-machine offline portability are not certified here.

From the existing trusted checkout, choose an existing private output directory:

```sh
AW_PY=/absolute/path/to/trusted/python3.12
AW_SRC=/absolute/path/to/checkout/v2/apps/workspace/src
PYTHONPATH="$AW_SRC" "$AW_PY" -m agent_workspace.cli version
PYTHONPATH="$AW_SRC" "$AW_PY" -m agent_workspace.cli source-kit --output /absolute/private/pilot.zip
PYTHONPATH="$AW_SRC" "$AW_PY" -m agent_workspace.cli verify-kit --archive /absolute/private/pilot.zip
```

Verify before extracting to a **new** empty local directory. The manifest catches
corruption; it is not a signature and does not establish publisher trust. The kit
includes neutral source paths, a Python lock and a pnpm lock with only the neutral
frontend importer. Unused public package resolution metadata is retained for lock
consistency; it is not an installed-runtime SBOM.

For a same-host pilot, explicitly select and bind existing trusted dependencies:

```sh
AW_KIT=/absolute/path/to/new-extracted-pilot
AW_MODULES=/absolute/path/to/existing/trusted/frontend/node_modules
AW_PY=/absolute/path/to/existing/trusted/python3.12
unzip /absolute/private/pilot.zip -d "$AW_KIT"
ln -s "$AW_MODULES" "$AW_KIT/v2/apps/workspace-web/node_modules"
ln -s "$AW_MODULES" "$AW_KIT/v2/node_modules"
cd "$AW_KIT/v2/apps/workspace-web"
WORKSPACE_PRODUCTION_BUILD=1 node "$AW_MODULES/next/dist/bin/next" build --webpack
AW_SRC="$AW_KIT/v2/apps/workspace/src"
PYTHONPATH="$AW_SRC" "$AW_PY" -m agent_workspace.cli preflight --data-dir "$AW_KIT/local-data" --web-dir "$AW_KIT/v2/apps/workspace-web" --node-modules "$AW_MODULES" --api-port 8130 --web-port 3130
PYTHONPATH="$AW_SRC" "$AW_PY" -m agent_workspace.cli launch --simulation --production --data-dir "$AW_KIT/local-data" --web-dir "$AW_KIT/v2/apps/workspace-web" --node-modules "$AW_MODULES" --api-port 8130 --web-port 3130
```

The dependency symlink above is an explicit local operator choice; no archive
symlinks or automatic discovery of legacy dependencies are trusted. The supported
Next output is the single reusable `.next-build`. Stop with Ctrl-C; the launcher
cleans its own process groups. Direct API startup also takes an exclusive file
lock before constructing or changing the catalogue, even without a model.

## First project

Open `http://127.0.0.1:3130/workspace`. Create a project, import a synthetic text
source, write a brief, then send the exact mock command `fixture:create` for a
deterministic draft (or `fixture:research` for the packaged offline research
journey). These commands are test fixtures, not evidence of general-language
model understanding. Review and edit the artifact, inspect
history and retained sources. A SIMULATION label is expected and is not evidence
of real reasoning quality. Use Local pilot in Settings to download content-free
authenticated diagnostics. Those include owner-scoped counts, safe versions,
offline checks and the backend Python source fingerprint only. Do not share a
database backup in place of diagnostics.

## Private backup, compatibility and restore

Drain runs and reconcile uncertain effects first; then stop the runtime. The
offline backup acquires the same ownership lock and refuses an active runtime,
in-flight application work or nonterminal DBOS workflows. It preserves all private
catalogue history, session hashes, audit/effects, source and artifact versions,
memory, grants and manual schedules. Browser-local drafts and provider secrets are
not part of the data backup. Backups are **private, not redacted or shareable**.
AW08 uses explicit format-v2 metadata and two additive review tables. Recognized
AW07 format-v1 backups can be restored into a new directory, but keep the v1 marker
and cannot start AW08 until the stopped `upgrade-data` command below is run. That
command adds the review tables and atomically replaces the metadata marker. A
failure between schema/marker steps refuses startup, preserves the original
private backup and can be completed by rerunning the explicit stopped upgrade.
Unknown/future schemas are refused. Upgrade never marks pending runs as completed
or starts jobs. Stop old workers first; do not share a catalogue between versions.
The new lock cannot protect against an already running older AW06 process that
does not participate in this protocol. Stop all previous AW06 instances manually
before the first AW07/AW08 offline backup/upgrade; do not run old and new versions together.

```sh
mkdir -m 700 /absolute/new-private-backups
PYTHONPATH="$AW_SRC" "$AW_PY" -m agent_workspace.cli backup --data-dir /absolute/data --output /absolute/new-private-backups/backup.zip
# For a recognized AW07-v1 or unversioned AW06 directory, after private backup:
PYTHONPATH="$AW_SRC" "$AW_PY" -m agent_workspace.cli upgrade-data --data-dir /absolute/data
PYTHONPATH="$AW_SRC" "$AW_PY" -m agent_workspace.cli restore --archive /absolute/new-private-backups/backup.zip --destination /absolute/new-restored-data
```

Restore verifies bounded archive paths, sizes, hashes and database integrity before
publishing a **new** directory atomically. Existing destinations are never
overwritten; future/unknown data and pending workflows are refused. A SHA manifest
does not make an untrusted backup safe or authentic: restore only your own trusted
private backups. No restore command launches replay, jobs, effects or schedules.
The restored permissions and sessions remain private operator responsibility.
Start the restored directory explicitly only after inspecting preflight. Keep the
original data/backup unchanged until the recovery check passes.

If preflight reports `runtime_locked`, stop the owning runtime; never delete a
lockfile or kill unrelated processes. `port_busy` means select unused loopback
ports. `data_upgrade_required` means the explicit stopped backup/upgrade flow
above. For unknown/future data, preserve the original and use a matching supported
version; do not edit version markers to bypass compatibility checks.

## Review and selected deliverables

Focused/grid/raw editing saves a new version only after explicit server ACK.
Agent review is an optional per-run context flag on an exact saved artifact/version.
Use `fixture:review` for a document with two scripted change regions, or
`fixture:review-table` for a CSV with a header and at least three data rows. These
are transport fixtures, not evidence of real language understanding. Pending
proposals do not change saved versions. Choose independent change IDs or all
changes and accept once, or reject. A stale base, unfinished/failed/cancelled
producer or revoked privacy scope cannot publish. Keep the proposal and your draft
on conflict; start a new review from the current saved version rather than rebasing
silently. Partial CSV changes operate on logical rows, preserving string values;
the saved CSV may use normalized LF/quoting, and invalid mixed shapes fail atomically.
Canonical content remains bounded at 256000 UTF-8 bytes, with at most 4000 diff
units, 100 independent changes, eight candidates per run and 128 retained
candidates per workspace. Exhaustion is explicit; this pilot does not silently
delete pending proposals or introduce an automatic retention policy.

Selected handoff chooses at most ten distinct saved artifacts, one exact version
and supported format each. Unsaved edits and pending proposals are never included.
The ZIP contains selected outputs and a version-1 manifest only, not conversations,
memory, unselected sources, permissions, credentials or runtime data. Manifest
hashes show captured content/export integrity, not approval or imported authority.
DOCX/PDF use existing bounded projection renderers; bundled Noto fonts and their
license are shipped for offline PDF Unicode rendering. CSV safety prefixes may
appear in exported formula-like values and are disclosed in warnings; canonical
saved string values are not changed. Real AI and human semantic acceptance remain
unmeasured.
