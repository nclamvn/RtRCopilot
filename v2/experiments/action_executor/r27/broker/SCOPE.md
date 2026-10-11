# R27 owned broker — approved implementation continuation

2026-10-10 · Contractor · same consolidated R27, not R28.

## Approval and architectural boundary

Homeowner said "chốt và triển khai" immediately after the concrete recommendation:
an owned host broker controls qualifying artifact/stream writes; Codex/platform
transcripts are separately retained audit, not the qualifying artifact packet.
This approves that architecture and its local implementation. It is not campaign,
provider, SQL/Docker/HTTP, production, Git write/rebuild, executor activation or
TIP-054.5 authority. No further approval is needed for routine local implementation.

The immutable R25 contract remains the historical base. Pin it directly together
with boundary.json; change ONLY the approved platform-audit boundary for this
new candidate. All original shell/admin/child stdout/stderr, terminal/failure/
cleanup/temp/artifact copies remain qualifying output, never silently excluded.
Platform audit is explicitly disclosed and not asserted zero or broker-controlled.
Preserve sealed retention/runtime candidates, reports, bindings and old failure epochs.

## Concrete implementation

One typed host Broker exclusively performs admitted artifact file I/O, framing,
physical copies, overwrites, temp lifecycle, flush and seal. Producers receive
opaque logical ports/Path facades with byte/stat snapshots; NEVER physical storage
paths, raw file objects/descriptors or writable broker root capabilities.
Use explicit source-connected adapters, not interpreter open/mkdir monkeypatching
as a claim of native prevention. Source read witnesses use pinned normal readonly
access outside the active producer facade. Broker private storage can be passed
to Main/recovery as owner only, never to the controlled child.

Same logical10MiB aggregate, whole raw bytes, no refund on overwrite/delete/failure,
same20 family count/payload bounds, closure/control/metadata reserves as historical.
Every retained frame/raw payload/physical write is charged before broker I/O.
Prevalidate record family/domain AND combined/metadata budgets before destructive
open/truncate/write. Sticky INCOMPLETE on excess/unrouted/path/symlink/storage faults.
No truncation, read-chunk splitting or digest replacement to obtain PASS.
Strict recovery reconstructs writes/deletions and validates all live owned files.

Implement useful real source integrations: exact original journal retain,
summary/write/print/oracle/final blocks; full pure signed fixture fivefiles/sixwrites
and read/stat through the facade; actual audit sink; original R21 copy/literal/
review/returncodes; R19 actual cleanup deadline writer/metadata bodies. Original
effectful Bash invocation, full publish/staging/SQL/migrations remain unexecuted.
Map every original family to endpoint/status honestly; empty receipts != coverage.

For unchanged fixed raw-child controls, each bounded entire stdout/stderr stream
at EOF is ONE record per stream, not read chunks, lines or framed invented payloads.
Cap receive memory before growth; reject oversize without retaining partial output.
Unrestricted original app/native emitters need producer-aware record admission,
otherwise capability-DENY/PREPARED. Do not advertise arbitrary native pipes as
covered by a new framing protocol; no need to build such a protocol in this batch.

Local supervisor owns exact created child, concurrent pipe drains, one monotonic
cleanup deadline (never renewed), shielded joined terminal cleanup on first/repeated
cancellation, overflow and primary/storage faults. Child gets minimal env, no root
argument/env/cwd/pass_fd. Keep exact cancellation/primary exception identity.
Do not claim original Linux /proc group, descendants or physical SQL lease proof.

Threat boundary: supported source-bound cooperative producers and exact owned
finite child; not hostile same-UID/privileged host processes, Python introspection
or a universal OS sandbox. A cached native open(os.fspath(facade)) must fail before
artifact I/O because the facade is not an OS path; unknown native writers are
rejected in admission, not converted into proof of OS-wide prevention.
Main/controller private paths are trusted owner state. Independent filesystem
tamper must fail recovery; do not assert all external writes can be prevented.

## Acceptance within R27

- B1 Approved audit boundary pinned, disclosed, base contract unchanged.
- B2 Actual sole-writer/opaque ports, pre-I/O whole budgets, physical copies, temp
  deletion/overwrite accounting and strict recovery with raw fidelity.
- B3 Real pinned producers connected without file-hook dependence; exact fixed child
  raw EOF outputs and supervisor fault/cancel/cleanup tested; no generic family PASS.
- B4 Source freeze, reproducible default-DENY preflight and actual local regressions,
  typing/lint/syntax zero in defined authored scope, independent review and one
  current consolidated Completion/Verify. Remaining unexecuted prerequisites explicit.

Tests: success, binary/text, empty/overwrite/delete/copy, temp namespace, cached
native API denial before I/O, source-eval faults, cap/record/metadata overflow,
shortwrite/flush/seal/cleanup, missing/extra/symlink/corrupt recovery, hook/stream
restoration if scoped redirects used, stale/foreign capability, repeated cancellation,
owned exact child reap/drain and primary exception preservation. Native unsupported
and synthetic grant cannot authorize effects. Preserve failed attempts and source
epochs before repairs; same tests repeated are overlap, not new coverage.

Freeze one candidate with exact source inventory, boundary/base/old-source anchors,
HEAD+dirty bytes, resources/new broker epoch+fresh marker, all old SLA/load settings.
No consumed marker reuse. Preflight always denies launch in this batch; source/
platform boundary match can PASS without pretending live fixture/capacity/DB/group
prerequisites ran. Do not remove native capability blocking merely because new
broker endpoints work. Goal is meaningful implementation/verified closed local
paths, not a paper certification of unexecuted whole runtime.

## Roles and artifacts

Builderlead owns core writer/facade/recovery/core tests/binding/aggregate checks/
Completion; peer owns source producer bridges/local supervisor/routing/preflight/
integration tests. Agree interfaces internally, no overlapping edits.
Contractor owns this scope/boundary/current Verify/status; Reviewer source-only
independent final check. Normal fixes and bounded test iterations stay internal.
Read this scope completely before implementation.

Work in this checkout, existing pinned venv only. No project copies, installs,
per-task build dirs or Docker; caches disabled/devnull. Scratch tests under new
broker directory auto-clean. Main will rerun frozen controls/static health and
verify all old pins/product204/tests192/dependencies unchanged.
