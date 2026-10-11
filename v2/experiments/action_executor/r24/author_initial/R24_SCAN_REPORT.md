# R24 — Whole-capture producer audit

2026-10-10 · Builder · Offline source/evidence analysis only.

## Result

Whole-capture admission is **HOLD**. The complete source upper bound is unknown,
not 10 MiB minus a reserve. The existing polling STOP does not impose an ex-ante
bound: stdout/stderr go directly to files, checks occur every 0.02 seconds and
after the child, and process/cleanup/check output can be written after a check.
Neither 190 seconds nor shared 10-second cleanup bounds emitted bytes.

The machine ledger covers 20 producer families and all 63 historical R21 HTTP
root files exactly once: 943,953 bytes. The separate consumed launch marker is
287 historical bytes outside that root. Live `tmp`/staging files, optional stop
outputs and outer shell/Main transcripts are explicitly accounted for even though
absent from that historical file set. PRE has a separate 10 MiB root; its passing
evidence is not silently added to the HTTP cap or represented as free bytes.

Three contributions are genuinely fixed for these pinned R21 source targets:
binding + contract copies, 5,646 bytes; OFF controls JSON, 283 bytes; executor
scope literal with newline, 117 bytes. Their 6,046-byte subtotal is not a complete
bound. Exact future binding size must be derived afresh, not inherited.

## Concrete obstruction

The original driver retains compact JSONL and a pretty final JSON copy of the
same records. Its 16-cell summary is also retained twice (file and stdout, the
latter with one newline). Successful scheduling supplies at most 1,600 distinct
attempted slots, but the recorder appends to memory before write/flush: a recorder
exception can cause another exception-row append for the same slot. Missing
descendants, aborted summary and partial writes are failure cases, not repairs.

The driver and validator do not establish finite serialized string domains for
every error/state/exception value. This is a missing proof, not an observation
that the driver actually emitted arbitrarily long strings. Normal finite numeric
values and one-record fixture assumptions also do not prove all failure paths.
Generic logging, migration diagnostics, Python tracebacks, supervisor/ownership
errors, Docker/PostgreSQL/admin errors and interrupted temporary files have no
complete producer byte contract. Normal empty stderr is not a zero upper bound.

Owner/result JSON duplicates ownership data. Source CLI calls print small ACKs,
not the snapshot JSON; the wrapper copies the binding once. Fixture, disk, source,
cap, child, postload, return-code, DROP and closure outputs are separately counted.
Administrative timeouts and free-space thresholds are not output bounds.

R23's 1,281,810-byte wire figure is a nominal synchronous model only. Real
fallback/error/repeated-cancellation coverage and async transparency are unproved.
The old ON phase profiler/PG monitor is a different, unadmitted implementation.
No installed observer, actual scheduling equivalence or zero overhead follows.

## One actionable next design (not implemented or admitted)

Request a focused future **bounded-producer envelope** design, not another
attribution run. It must define source-derived count and byte domains for every
producer, whole-record framing, repeated copies, live temporary files and reserved
terminal/ownership/cleanup metadata. An owned ex-ante writer must admit each whole
record before writing, with no uncapped stderr/finally escape route. Oversized,
unsupported or saturated output must produce an explicit INCOMPLETE/STOP packet;
it cannot qualify a measurement, silently trim raw, suppress an error, or retry.

Lossless arbitrary stderr plus unchanged producers plus a fixed finite cap cannot
all be promised. The design therefore needs Main/Homeowner approval for a narrowed
future experimental output contract (including finite failure representation) and
its error-fidelity/transparency proof before implementation. A pre-write limiter
alone only bounds an incomplete failure artifact; it does not establish complete
capture. Do not relax 10 MiB, 190 seconds or shared 10 seconds. Do not change the
original helpers or run a campaign in R24.

## Verification scope

`r24/audit.py` uses stdlib source parsing/hashing only. It derives the three fixed
contributions, rejects a promoted numeric/prose proof, and leaves unknown totals
null. `test_audit.py` has six memory-only control groups; model fit never grants
capture. Before/after checks expand the existing linked seals, verify full declared
product/test inventories and pin R23 final reports/closure/publication bytes.
Published mutable status/taskgraph hashes remain historical metadata.

Actual feedback and commands are in the Builder Completion and `author-feedback.json`.
No product/helper import, workload, SQL, Docker, HTTP, network, signals, Git, build
or install is used. Runtime budget/transparency gates remain separate and open.
