# R25 — Bounded producer envelope proposal

2026-10-10 · Builder · DESIGN and pure offline model only.

## Scope and source facts

Python stdlib only; no runtime framework, DB, auth override or environment change.
R24's complete 20-family ledger is the source-linked inventory. Its three fixed
contributions total 6,046 bytes; all other current maxima remain null. Historical
R21 size and R23 nominal wire size are not future guarantees. Original R19 direct
streams/polling and R21 helper/wrapper/temporary writers remain unchanged.
The 190-second load / 120-second other-child and shared 10-second cleanup limits
remain unchanged; this memory model does not simulate or prove those deadlines.

The proposal is one exclusive future epoch boundary: all HTTP copies, direct
streams, outer shell transcript, sibling marker, live temporary writes and terminal
metadata share 10 MiB. PRE would have its own separately bounded 10 MiB context;
it cannot establish HTTP fit. Downstream offline reports/seals are provenance, not
free output inside an admitted epoch. Every extra physical copy must be charged;
no unaccounted alias, native file, stdout/stderr, finally or supervisor route.

## Proposed domains and exact model budget

Every allocation below is a **new contract choice**, not an existing producer
bound. `contract.json` carries each R24 source witness/hash, original classification
and original maximum separately. The original source set is not imported/executed.

| Family | Proposed count × maximum payload bytes |
|---|---:|
| Frozen binding/contract copies | 2 × 65,536 |
| OFF controls | 1 × 512 |
| Scope literal | 1 × 256 |
| Review + sibling marker + ACK | 3 × 1,024 |
| Journal | 3,200 × 512 |
| Pretty final samples | 1 × 2,097,152 |
| Summary file + stdout + remaining stdout | 3 × 16,384 |
| Load stderr | 4,096 × 512 |
| Migration streams | 512 × 512 |
| Owner/process copies/updates | 8 × 1,024 |
| Supervisor/stop | 64 × 1,024 |
| Source/cap/child proof | 32 × 2,048 |
| Fixture checks | 8 × 8,192 |
| DB/admin/cleanup output | 64 × 2,048 |
| Disk checks | 8 × 4,096 |
| Reconstruction/error output | 2 × 65,536 |
| Return codes | 32 × 256 |
| Live-file writes/copies | 16 × 65,536 |
| Future observer (not installed) | 40,000 × 32 + 1 × 1,810 |
| Outer transcript | 128 × 1,024 |

Record framing is big-endian `family:u8, variant:u8, sequence:u32, length:u32`,
then exact raw payload bytes and LF: **11 bytes per record**. Limits apply to
encoded bytes, not characters. There is no digest substitute, redaction, error
code replacement, truncation, deduplication or splitting of an oversized logical
record to evade the limit. Each producer must define its logical record boundaries
before adoption; the present sources do not supply all of these boundaries.

Normal record maximum: **9,778,276 bytes**. Twenty closure receipts are 16 bytes
each; one terminal is 20 bytes. Terminal/closure metadata reserve: **340 bytes**.
`cleanup_ok` is only a modeled prerequisite acknowledgement; actual DB/process
cleanup proof must be retained through normal producer families and independently
verified. Reserving terminal space proves neither cleanup nor quiescence.
Complete proposed aggregate: **9,778,616 bytes**; spare: **707,144 bytes** within
10,485,760. The spare is not proof of unrestricted diagnostics. R23's original
32-byte event figure is not reused as a runtime bound: the proposed observer data
payload gets another 11 bytes of envelope framing, plus its distinct framing record.
For a valid closed contract, its full summed maximum is below the cap, so aggregate
OVERFLOW is an invariant defense, not a reachable saturation scenario in that
golden run. Controls separately reject an over-cap proposed contract and exercise
per-family count/payload saturation; they do not claim an actual cap-stop run.

This monotone model charges every attempted whole write before persistence,
including repeats and live-file copies; partial storage failure burns the full
reservation. It never refunds on overwrite or deletion—even acknowledged deletion.
This conservatively bounds a modeled high-water footprint; actual file/allocation
overhead and exclusive ownership still need proof. It does not count a raw file
and its retained copy as the same free object. No existing `TemporaryDirectory`
or imported writer is routed through this model.

## State, closure and failure fidelity

OPEN accepts only exact bytes under the known family/variant/sequence domains.
Unknown/malformed, oversized, saturated or declared bypass output enters sticky
INCOMPLETE and stops normal emission. Accepted raw error bytes are retained
unchanged; unsupported raw is not represented and therefore cannot qualify capture.
An incomplete terminal reason identifies a control failure, not preservation of
the rejected diagnostic. A hash of unretained data would not repair this.

Each family has exactly one attempted receipt, freezing admitted attempt count
and charged bytes. Zero-emission receipts are explicit owner acknowledgements,
not inference from an empty observed file. Emission after that receipt and repeated
closure are invalid. The future adapter must prove quiescence/exclusive ownership;
the model cannot discover undeclared bypass writers. All 20 receipts and an
acknowledged cleanup prerequisite are required before COMPLETE_MODEL.

Receipt and final writes use only the reserve. Persistence failure, missing
receipt, cleanup failure, rejected output or post-closure misuse cannot produce
model completeness. A single final attempt freezes the epoch; TERMINAL/CRASHED
states never reopen, and faults do not emit a second terminal or unlimited records.
Partial terminal storage or crash provides **no guaranteed durable STOP**. An
intact bounded INCOMPLETE control record may be acknowledged in memory, but actual
durability is never proved here. A final frame alone is not exclusive-writer proof.
Verdicts apply to the live model object, not recovery from its byte list. A stored
COMPLETE frame can precede an unacknowledged write or post-terminal misuse; no
reader/replay protocol is implemented. Future authoritative epoch sealing and
exclusive writer teardown must reject that uncertainty before recovery acceptance.

COMPLETE_MODEL only means all declared supported synthetic records were retained
under this proposed contract. It does not repair missing descendants or change
the original helper summary/oracle, SLA outcome, timers or timeout classification.
Actual capture admission is always HOLD; latency/performance equivalence and
runtime readiness are never outputs of this model.

## Exact next authority and remaining proof

Main/Homeowner must explicitly adopt or reject this narrowed experimental output
contract before authorizing an owned adapter. Approval would need to name the
future source changes: all original journal/final/summary writers, generic logging
and migration streams, native temp/file paths, supervisor/process/bookkeeping,
admin/outer transcript and sibling marker must enter the same pre-write ownership
boundary. Existing R19 polling cannot implement it unchanged. No such adoption or
implementation is authorized in R25.

The next authorized implementation would require finite producer record schemas,
complete failure/raw fidelity and bypass discovery, actual durable reservation/
partial-write handling, cleanup/closure quiescence, concurrency/locking, origin-
identity/path equality, exact async scheduling/cancellation and restoration proof.
Do not wrap `ActionPolicy.current.__func__` or silently change trusted factories.
No additional independent I/O/yields/tasks is an intention, not synchronous proof.
Only after these source/adapter gates could Main request a separate finite runtime
admission; this design grants no campaign, SQL, observer or serving activation.

## Delivery and health

New small `r25/contract.json`, `model.py`, `test_model.py`, `checks.py`, linked input
binding and actual feedback. Six memory-only control groups; builtin syntax checks.
No prior helper import, SQL/Docker/signals/HTTP/external/Git/build/install/scratch.
R24 seals/closure/publication and full 204/192 inventories are hash-checked before/
after. Historical mutable publication hashes remain point-in-time metadata.
Final feedback/Completion report exact counts and not-run health; Main/Reviewer
own acceptance and status publication. R21 SLA FAILED/P1, EXE-009 OPEN/P1,
candidate NOT_READY, serving executor OFF and .5 BLOCKED remain.
