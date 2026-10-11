# R26 — Independent owned-adapter review

2026-10-10 · Scoped isolated prototype accepted; no blocking finding.
Actual capture remains **HOLD**. Candidate NOT_READY, EXE-009 OPEN/P1,
serving executor OFF and TIP-054.5 BLOCKED remain unchanged.

Reviewed frozen binding:
`999167124e38280545959522e25dcc00e4b596779b5e01a74fb9e2601a82abd0`.

## Source and recovery verdict

I read the full TIP, R25 format/Verify, adapter/tests/checks, SCAN/Completion,
budget/binding and actual Builder/Main feedback. No adapter, model, helper or
product was imported or executed by this Reviewer.

The concrete protocol supports the declared local scope:

- `r26/adapter.py:129` binds actual rules to parsed hashed contract bytes before
  filesystem effects. Fresh directory creation, no-follow descriptor-relative
  regular files and real exclusive owner flock prevent cooperative competing/
  stale writers; RLock serializes calls. Validation failure closes raw descriptors.
- Lines 195–205 charge whole frames before writes; partial attempts never refund.
  Lines 209–233 allow one receipt per family and one final attempt. Malformed,
  oversized, saturated or failed writes cannot seal a complete packet.
- Lines 234–257 sync packet and seal, verify grammar/file set, charge the temporary
  and committed seal paths, then directory-sync before releasing ownership.
  Failed precommit invalidation retains the lock; `abandon` unseals before closing.
  The tested stale-seal case cannot escape through a public `release` method.
- Recovery (lines 285–318) requires shared-lock acquisition, exact file set,
  owner/epoch/contract/directory identity, bounded lengths, seal digests and exact
  frame/sequence/receipt/count/terminal grammar. A COMPLETE frame alone is not
  accepted. Re-signed test mutations exercise grammar beyond checksum rejection.

Committed epochs are deliberately immutable: late API calls reject before I/O
(`_active`, line 171). Tests compare all file hashes and recover the earlier sealed
packet afterward. COMPLETE describes that earlier packet, **not** successful late
calls or R25's mutable live-object semantics. Actual append/corruption/extra files
are rejected at recovery. This explicitly narrowed semantics is accepted.

## Independent arithmetic and preservation

Inline stdlib hashing/AST/struct arithmetic, without experiment imports, confirms
48,182 proposed records: 9,778,276 normal bytes +340 receipt/terminal bytes.
Owner and seal formats are each 88 bytes; owner +temporary seal +simultaneously
live committed seal are conservatively charged 264 bytes, below the allowed
4,096 extension. Maximum charged total **9,778,880**, spare **706,880** under
10,485,760. Final three-file maximum is **9,778,792** after temporary-seal removal;
charges are not refunded. All sidecars are included. These are logical encoded
byte limits, not filesystem-block overhead or bounds on unrestricted producers.

All 1,809 prior pins /13,749,891 bytes and 1,814 total pins /13,790,869 bytes match.
The prior manifest `26c83990cc6afc9545cad34eca9aa82954c63bb8ecb2254838cb425017011621`
matches Main. Full product204/tests192 inventories and declared digests match;
R25 final seal/closure/publication and linked earlier evidence remain unchanged.
Historical mutable status hashes remain point-in-time metadata.

## Actual evidence and limits

Builder's seven unique real-file groups passed in 0.367425 seconds; Main's same
seven passed in 0.391385 seconds, not fourteen unique tests. Both have zero
failures/errors/skips, syntax3 and unchanged before/after source. Tests cover raw
roundtrip/full budget, malformed/count/closure errors, injected write/flush/fsync/
seal/invalidation faults, active/stale ownership and eight-thread calls, strict
corruption/identity/grammar recovery and unsafe paths. Before/after sandbox lists
are empty; my read-only check also finds none. Actual Main structural/preservation
records agree with my independent checks.

R26-001 through R26-003 are accepted; independent/Main evidence for R26-004 is
accepted, with final Verify/publication owned by Main. Local tests are not power-
cut, true process-death or hostile same-UID/root certification. SHA digests are
integrity checks, not adversarial authentication. Cooperative locks/path checks
do not promise prevention of arbitrary hostile writes or filesystem races.
Failed cleanup retains ownership/uncertainty; no guaranteed durable STOP follows.
Lint/types/build and measured/async/SQL/Docker/HTTP/native/provider checks were
NOT RUN, not zero-error certifications. No 1,600-sample, original SLA, unrestricted
log-fit, latency-equivalence or application-cleanup proof follows from recovery.

One next prerequisite: separately authorize a bounded producer-routing integration
with exhaustive channel/bypass and raw-fidelity checks, then origin/path, async
cancellation/restoration and real cleanup/quiescence verification. Keep the cap and
reference deadlines unchanged. This review grants no measured integration,
campaign, observer or serving activation.

Only this new report was written; no old inputs, source or publications were edited.
No Reviewer tests, runtime, scratch resources or cleanup operations were performed.
