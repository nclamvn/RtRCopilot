# R26 — Isolated owned file adapter

2026-10-10 · Builder · Concrete local prototype, not measured integration.

The adopted input is unchanged R25 contract data, not its code. New stdlib
`adapter.py` writes actual owned files and provides strict recovery; local tests
use automatically removed directories inside `r26`. No prior helper/product import.

Data framing remains 10-byte header + payload + LF; 20 family receipts and one
terminal retain the 340-byte reserve. New fixed binary ownership/seal structures
are each 88 bytes: owner magic/epoch/token/contract digest/device/inode, and seal
magic/owner digest/packet digest/size/cap. The temporary seal and committed hardlink
are independently charged while simultaneously live. Control maximum is
88 + 88 + 88 = **264 bytes**, below the allowed 4,096-byte extension.
Prototype maximum is **9,778,880 bytes** (R25's 9,778,616 + 264), within 10 MiB;
the final three files use 9,778,792 bytes at the full record ceiling because the
temporary seal is removed. Charges are monotone, including partial attempts.

The writer creates a fresh epoch, uses exclusive/no-follow descriptor-relative
files, holds a real exclusive owner-file flock and serializes calls with an RLock.
It rejects unsafe/symlink/outside-r26 paths and existing/stale epochs. Identity
binds contract bytes, random owner token, supplied 16-byte epoch and actual directory
device/inode. Reader takes a shared nonblocking lock; active writer prevents recovery.
The complete file set, exact owner/seal size, whole-packet digest, family/variant/
sequence/length/count/receipt snapshots, zero-emission markers and single final
frame must all agree. Extra files/bytes, corruption, mismatch and unsealed artifacts
cannot recover as prototype-complete. Supported raw bytes are not normalized.

All record/copy budgets are admitted before writes. A failed partial write burns
its full reservation; no retry/refund or silent repair. Each receipt and final gets
one attempt. Write/flush/fsync/link/directory-sync fault seams perform real local I/O
and prevent qualification. Before successful commitment, failed finalization removes
seal state; if invalidation fails, ownership lock remains held until explicit abandon
successfully unseals. There is no public release escape. An intact COMPLETE frame
alone is insufficient. Failed sealing, controlled unsealed descriptor release or
missing metadata never supplies guaranteed durable STOP.

Committed epochs are immutable: successful seal closes writer descriptors. Later
API calls fail before I/O as separate caller misuse; tests compare the entire file
hash set. Reader completeness describes the earlier committed epoch only—not those
later attempted records. Append/tamper through a bypass is detected at recovery;
cooperative ownership does not prevent arbitrary hostile same-UID/root writes.
This is not a sandbox, power-cut, real process-death or filesystem durability proof.

Seven local test groups cover raw roundtrip/full budget, unsupported and late
records/closure, real I/O fault seams, active/stale ownership/concurrency, strict
corruption/grammar/identity recovery and unsafe paths. Controlled re-signing of
test mutations exercises parser checks beyond digest mismatch. All test-created
directories are owned under `r26` and removed even on test failure.

Preservation expands R25's final binding/seal/closure/publication plus prior linked
graph and complete product 204 / tests 192 sets. Historical mutable status hashes
remain metadata. Source feedback and Completion give actual counts and not-run
health; no Docker/SQL/HTTP/signals/network/Git/build/install or scratch copies.

Actual capture remains HOLD. The next prerequisite is a separately authorized
measured-writer integration with exhaustive producer/bypass routing, error fidelity,
cleanup/quiescence and origin/async/cancellation/restoration verification. The local
prototype does not prove 1,600 samples, original SLA success, latency equivalence,
runtime log fit, worker safety or readiness. Keep 190-second load/shared 10-second
cleanup references unchanged; no measured deadline is run here. EXE-009 OPEN/P1,
candidate NOT_READY, serving executor OFF and .5 BLOCKED remain.
