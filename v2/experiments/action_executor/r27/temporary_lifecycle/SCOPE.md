# R27 · Genuine tempfile / pytest lifecycle closure

2026-10-11 · Contractor/Main · P1 · one continuation, no new campaign/TIP.
Workdir: /Users/os/RtR/KnowledgeBase/RtR_Copilot.

## Authority and decision

Human requests: “Bước tiếp: đóng vòng đời tempfile/pytest thực, gồm đường lỗi.
Toàn gói vẫn NOT_READY; executor OFF, chưa chạy campaign, SQL/Docker hay external.”

This explicit next-step request authorizes bounded local implementation and tests
of genuine lifecycle bodies. Main adopts the finite sibling diagnostic policy
below for that purpose; it does NOT alter the already adopted pre_stage nine-path/
35-write contract, old HTTP policy, shared 10MiB cap or serving authority. No new
human checkpoint is needed for these technical local bounds. Any increase of cap,
unowned native fallback, arbitrary FD/path export, output omission, fault clearing,
global filesystem interception or uncontrolled child dispatch is a scope change.

Use vibecode Builder/Contractor separation and source-only independent review.
Focused scan and design are complete. Reuse existing algorithms, not copied projects
or reconstructed cleanup simulations. One Scope/Completion/current Verify; no RRI
or micro-approval loop. Tests are serial, with Main repeating one frozen entry.

## Design and finite policy

Sibling temporary_lifecycle has its own canonical local contract, epoch and frozen
checked entry. Existing implementation/evidence/contract trees are immutable anchors.
Bind installed Python3.12.11 tempfile/shutil and pytest8.4.1 sources before imports/
composition/effects. Run genuine selected bodies with private OS/Path/shutil globals;
no shared-module monkeypatch, unsafe rmtree substitution or fake success.

Use the platform-selected safe-fd walker (actual host selects true), including
lstat/open/fstat/samestat/scandir/DirEntry and dir_fd unlink/rmdir/finally-close.
Descriptors are private opaque owner tokens; underlying native descriptors/paths
are never given to arbitrary code. All successful operations reach the actual
owned native filesystem. Guard before creation, destruction, permission change,
write and symlink; validate owner/native identity and no external symlink traversal.

Finite local ceilings within SAME 10,485,760B/no-refund:
32 lifetime artifact names (files+links), 48 directories, depth8, relative path256B,
16 selected owned native descriptors, four owned links, 512 bridge transactions/
observations, 192 typed metadata
events, at most32 discovery/collision attempts each, and 64KiB metadata reservation.
Canonical metadata must fit BEFORE each relevant native action; these interacting
ceilings may deny earlier, not a universal claim that512 events always fit64KiB.

Counter clarification from actual source review: a whole-path transaction executes
native open/fstat/write/close; each of those steps/results/errors must be retained
and independently checked. The 512 bound is on pre-admitted bridge transactions
and observations, NOT every host syscall. Finite containment checks and readonly
source-pin/import I/O are separate guard work; no universal syscall/OS bound is
claimed. Four fixed capture-control descriptors (manifest plus packet root/owner/
data) are inside the selected 16 ceiling. At most12 remaining slots are shared by
producer descriptor tokens AND transient file-read/scandir descriptors; the three
pre-admitted stream/XML descriptors are producer tokens, not an extra allowance.
Admission applies before grouped writes and transient reads/scandir too. Readonly
source-pin descriptors are outside this selected producer domain, so 16 is not a
process-wide FD claim. No old bound/contract/implementation is modified.

Payload ceilings: original nine-path Cartesian1,201,440B /35 writes; small native
data24×4096B; link target4×256B; stdout/stderr two whole8192B streams; warnings/
callback messages4×1024B; one whole8192B XML. Total1,329,440B. At most70 raw frames;
conservative physical+packet+metadata+terminal+controls+closure maximum2,725,881B.
Coarse packet-only envelope is separate from this physical-copy proof. Enforce
actual typed domains/counts in live code; no uncapped second plane or stream dropping.

Probe open creates a retained empty-write attempt before native create; b'blat'
is retained/charged before the real os.write exactly once. Record requested and
returned bytes separately. Failed opens, short writes, overwritten/deleted payload,
symlink targets, warnings, errors and retries retain their charge/history. No raw
payload/frame may be unowned. Source loops (100/candidate, host TMP_MAX308,915,776,
pytest numbered10) stay unchanged; bounded admission aborts unsupported repetitions.

Default candidate aliases from genuine source must resolve only to declared owner
namespaces or deny BEFORE native access; no actual /tmp,/var/tmp,/usr/tmp/cwd fallback.
Read-only pinned source inputs are separate from output capabilities. Source naming
and finalizers must remain genuine; test fault inputs are explicitly distinguished
from real native results and from ordinary source execution.

Declared collision/discovery/recoverable permission controls may deliver original
exceptions to genuine source handlers within finite owned recovery state. Record
every attempt/error. They are NOT clearing a previously sticky terminal fault.
Unknown routes/authority denial/unexpected storage fault/short write remain absorbing,
unsealed. Genuine finally-close and a bounded cleanup-only capability still drain
owned resources; no new payload/creation after terminal fault. Preserve source return/
exception, first owner fault and cleanup failures separately without masking them.
Drain/detach actual finalizers before seal; no callback or descriptor may outlive
ownership. Source warning/error text must be retained, not swallowed by the harness.

### Failure-output decision · Main source review, 2026-10-11

The source checkpoint exposed that buffering streams/XML until normal return drops
partial outputs when source/owner faults. Adopt a narrow completion seam: before
dispatch, reserve the existing two stream slots and one XML slot, their complete
declared charge and native failure-retention/cleanup obligations inside the SAME
cap/count/metadata ceilings. Only these already-admitted outputs may finish their
bounded retention on unwind. This is not permission to create arbitrary payload,
add a second budget plane, refund reservations or clear a terminal fault. Pending
partial bytes must be physically retained with typed ownership for independent
inspection; a memory-only outcome is insufficient. Failure remains unsealed.
Success consumes these same reservations, not a second charge. Actual fault
controls must check partial XML, both streams, first cause and resource drain.
This clarifies completion of pre-admitted output, not expansion of producer roles,
old contracts, total bounds, campaign or serving authority.

## Acceptance criteria

| ID | Required output |
|---|---|
| H1 | Live canonical typed lifecycle contract and checked source admission, same cap/no-refund; all native write/metadata/name/fd/event/permission/link domains enforced before effects. Old PRE/HTTP/product/dependencies remain unchanged. |
| H2 | Entire unchanged original R21 setUp + rows/write_packet + corruption method + genuine unittest doCleanups through actual TemporaryDirectory/default probe/mkdtemp/safe-fd rmtree. Full35 writes/733169B and all original assertions are retained; creator/cleanup semantics and native bytes actually conserved. No setUp replacement or count-only oracle. |
| H3 | Real in-process pytest with private genuine tmpdir plugin, explicit given-basetemp, two tiny pinned tmp_path scenarios including intentional failure. Existing stale base removal, numbered directories/current symlink, source fixtures and sessionfinish/deadlink cleanup actually execute. Capture actual result/XML/stdout/stderr within shared budget. Nested intentional failure is expected source evidence, not a passing application case or extra outer scenario. |
| H4 | Probe fallback/collision, permission reset/chflags/chmod, mkdir/unlink/rmdir/scandir/descriptor-finally, warning/error/finalizer and cleanup failures are exercised using actual operations and explicit injected controls where appropriate. Distinguish those evidence types. No swallowed terminal owner fault or late callback, leaked FD, escaped native path, ignored output or fabricated syscall result. |
| H5 | Independent typed recovery binds raw-frame owners, actual requested/returned writes, inode/descriptor lifecycle, permissions, links, attempts/errors/callbacks/finalizers and final native conservation. Missing/extra/duplicate/tampered/cross-stage history rejects. Exact existing33 + five new outer controls serially pass; strict/Ruff/format/syntax, full old pin/inventory preservation, retained initial failures, frozen Completion/binding/candidate and Main/source Reviewer verification agree. |

## Remaining boundaries / claims

This closes selected genuine native lifecycle on the actual local Darwin environment;
not a hostile-process OS sandbox, universal tempfile API/plugin or Windows/Linux proof.
Given --basetemp bypasses default pytest user/.lock/PID/garbage-rename/atexit retention;
those remain DENY/unqualified. Arbitrary native subprocess/file writers and complete
six-suite/launcher PRE remain unqualified; do not launch them just to fill coverage.
Real campaign, SQL/Docker, providers/external processing, install/rebuild/Git writes,
production operations, executor activation and TIP-054.5 are out of scope.

R21 SLA FAILED/P1; EXE-009 OPEN/P1; full candidate NOT_READY; executor OFF; .5 BLOCKED.
Synthetic elapsed_ms=1.0/process/env fixture fields are source inputs, not measured
operations or activation. Local elapsed test time is not repaired executor latency.

## Hygiene / handoff

69GiB free checked; existing checkout/backend venv, no install/copy/new distDir/cache.
apply_patch for edits; bounded owned test roots cleaned on success/error. Preserve all
unrelated dirty changes. Before Main current-publication updates, retain four current
publication bytes/hash. Keep old artifacts immutable. Builder writes implementation,
tests, raw evidence and Completion; Main owns this scope/verification/publications.
Routine implementation fixes are internal; material changes escalate once together.
