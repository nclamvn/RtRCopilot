# R25 — Independent bounded-producer design review

2026-10-10 · Independent Reviewer · Design/offline evidence only.

## Verdict

Accept the scoped design and memory model, with the documented runtime deferrals.
No blocking discrepancy was found. **Actual capture/adoption remains HOLD / NOT
AUTHORIZED**, with actual source upper bound null. The 9,778,616-byte result is a
bound on supported proposed records, not on unchanged producers or unrestricted
diagnostics. R21 SLA FAILED/P1, EXE-009 OPEN/P1, candidate NOT_READY, serving
executor OFF and TIP-054.5 BLOCKED remain.

Frozen input binding:
`87c5aa1ad6cd8009aa7eacf607a060d258dde11c929653f265c4d7af53bf0923`.
Budget SHA-256:
`bef414c04a6f710ecb66b77c7b1b50902247e7759e34592c58039134327e103a`.

## Independent verification

I read the full TIP, R24 Verify/ledger, all three new Python sources, full proposed
contract/budget, SCAN, Completion, Builder feedback/provenance correction and
Main feedback/arithmetic/before/after checks. I did not import or execute these
modules, helpers, product code or controls.

Independent inline stdlib hashing expanded 1,787 prior pins / 13,634,646 bytes,
then 1,794 total pins / 13,692,658 bytes, all matching. Full product204/tests192
inventories and content digests match their declared sets. The prior pin manifest
`94295ba8ac1c58890dfda8b9cc3cf21d7dfaac18b03d60592a3c226ca6b7b0b5`
matches Main's before/after checks. R24 final seal/review/Verify/closure/publication
and linked earlier evidence remain unchanged; historical live-status hashes are
point-in-time metadata, not current-byte gates.

All 20 proposed families preserve the exact R24 classifications, current maxima
and source witnesses. Every nonfixed current maximum remains null. The new limits
are explicitly proposed allocations; the exclusive future boundary includes
copies, sibling marker, outer streams, temporary/live writes and final metadata.
PRE is a separate proposed cap, not proof of HTTP fit.

Independent serialization arithmetic matches every budget row:

- 48,182 maximum proposed data records; header `>BBII` is 10 bytes, followed by
  exact payload and one LF. Normal total: 9,778,276 bytes.
- Twenty `>cBIQBc` receipts ×16 bytes plus one `>cBBIIQc` terminal ×20 bytes:
  340 metadata bytes. Total: 9,778,616; spare: 707,144 under 10,485,760.
- Observer allocation includes its additional envelope framing:
  40,000×(10+32+1)+(10+1,810+1)=1,721,821 bytes, not R23's wire size alone.

The 340-byte reserve is terminal/closure metadata, **not cleanup proof**. Neither
allocations nor spare space establish original producer maxima or filesystem
allocation overhead. A valid summed proposal cannot reach aggregate OVERFLOW;
that branch is an invariant defense. Actual controls exercise per-family
count/payload limits and reject over-cap proposals, not an actual capture STOP.

## State and fidelity review

`r25/model.py:97` guards malformed identifiers before lookup; lines 114–123
encode and charge the whole attempt before modeled persistence. Counts/bytes are
monotone: failed partial writes burn reservations; overwrite/deletion cannot refund
them. Duplicate physical outputs are separate records, not free aliases.

Lines 125–135 freeze one receipt per family, including explicit zero-output
acknowledgement; emission after receipt cannot stale that snapshot. Lines 78–94
make faults sticky and persistence failures invalidate completeness. TERMINAL and
CRASHED never reopen; lines 146–162 allow only one final attempt. Controls cover
unknown/unhashable IDs, malformed payload/sequence/storage values, missing and
duplicate receipts, late emission, partial storage, cleanup failure and crash.

Raw accepted payload bytes are unchanged. Unsupported/oversized output is not
represented and makes evidence incomplete; a finite failure flag or digest is
not retention of rejected diagnostics. A zero-family receipt is an owner assertion,
not discovery of an empty channel. COMPLETE_MODEL also permits supported zero
emissions: it is not proof of 1,600 samples, original oracle success or semantic
measurement completeness.

The live-object/recovery limitation is explicit and essential. Full-length bytes
may exist without an acknowledged write; a stored COMPLETE frame may precede
post-terminal misuse. The live object then rejects completeness, but there is no
authoritative recovery/replay protocol. Failed terminal persistence or crash
does not guarantee durable STOP. Undeclared writer discovery, actual quiescence,
durability, concurrency, bypass prevention and teardown are deferred—not passed.
Similarly, memory allocation failures/real I/O failures and asynchronous scheduling
are not exhaustively simulated by supplied boolean persistence inputs.

## Actual evidence and acceptance scope

Builder's six unique controls passed in 0.042988 seconds, zero failures/errors/
skips; syntax checks covered three files. The wording-only reserve clarification
followed that run: old feedback retains binding `2d6e8c19…` /1,793-pin context;
the four code/contract hashes are unchanged and fresh final checks cover binding
`87c5aa1a…` /1,794 pins. I verified this provenance rather than relabelling the
old run as a final-binding execution.

Main's actual final-binding run (e6ccaf) passed the same six controls in 0.040388
seconds, not six additional unique tests, with syntax3 and before=after. Its
independent arithmetic/import surface and prior rehash agree with my checks.
Lint/typecheck/build and runtime/async/durability/SQL/Docker/HTTP/native/provider
checks were NOT RUN; their error counts are unavailable, not zero.

R25-001 preservation, R25-002 design/source mapping and R25-003 pure controls are
accepted. The review/Main evidence portion of R25-004 is accepted; Main owns final
Verify/publication. Four design criteria can close without closing runtime budget,
retention adoption or transparency gates.

## One next authority decision

Seek explicit adoption of the finite experimental contract and authorize only a
new owned adapter with local failure/recovery tests—no campaign or activation.
Before integration, name logical record boundaries and route all writers/copies/
live files through pre-write ownership; prove durable reservation, partial-write
handling, exclusive shutdown/sealing, bypass detection and error fidelity. Then
prove origin/path, async cancellation and restoration without changing guarded
policy/factory identities. Unchanged arbitrary sinks plus a finite cap still cannot
promise lossless complete capture. No further reserve-analysis loop, trimmed raw,
normalized error success or automatic runtime allowance is recommended.

Only this new report was written; no old source/evidence/publication edits,
runtime actions, scratch resources or cleanup operations were performed.
