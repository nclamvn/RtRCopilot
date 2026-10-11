# R24 — Independent whole-capture budget review

2026-10-10 · Independent Reviewer · Offline reads/hash/AST/arithmetic only.

## Verdict

Accept the scoped analysis and its **capture HOLD**. No blocking discrepancy was
found in the frozen ledger, outputs or actual control evidence. The complete
upper bound remains null; 6,046 fixed bytes and a historical packet below 10 MiB
do not prove complete capture fit. R21 SLA FAILED/P1, EXE-009 OPEN, candidate
NOT_READY, serving executor OFF and .5 BLOCKED remain unchanged.

Reviewed binding SHA-256:
`34f6c3f85d1c2468731b0ba0fa103d49c2fd71abc3af44811b71de507ce4ca00`.
Analysis SHA-256:
`2c38e4a7b5852b6341b026ca8b9a7f9c76d0b820d77346549e031d1caf3701f3`.

## Independent checks and source facts

I read the full TIP, ledger, audit, six control methods, SCAN, Completion, Builder
feedback/tool records and Main feedback/arithmetic/preservation/file coverage.
An independent inline stdlib reader, without importing any experiment, product
or helper, expanded and rehashed 1,762 prior pins / 13,498,377 bytes and 1,771 total
pins / 13,587,654 bytes. Complete product/test inventories remain 204/192; their
digests match `b28e70d1905930fd517576b7df73edc6710cf4bae273f137da5e75ffd155c641`
and `5039c2a6a47fa1566f84b1acf766c5d212f731e6c9127aeec08576c7663fadc1`.
Linked R21/R22/R23 seals, immutable final reports and R23 closure/publication
records match. Historical mutable publication hashes are not current-byte gates.

All 20 producer families reconcile the 63 historical R21 HTTP-root files exactly
once, totaling 943,953 bytes. The consumed sibling marker is separately 287 bytes,
outside that root. I verified witness hashes/line ranges and independently derived
the three fixed contributions: copied binding/contract 5,646; AST-derived OFF
controls 283; literal scope line including LF 117; subtotal 6,046 bytes.
These values apply only to the pinned targets. PRE has a separate cap; outer
transcripts and downstream provenance are not silently counted as zero output.

The decisive source witnesses are:

- `v2/experiments/action_executor/latency_probe.py:39` appends before JSONL
  write/flush. Lines 61–65 allow at most two retain calls per attempt after a
  recorder fault. The closed workload has at most 1,600 attempts, hence at most
  3,200 in-memory appends—not unbounded cardinality. With valid recording there
  are **at most** 1,600 unique rows; successful recording does not guarantee every
  descendant request occurs. The ledger's “gives1600” wording is interpreted as
  this ceiling, not a full-sample guarantee.
- The same file's lines 97–98 duplicate pretty summary bytes into a file and
  stdout (stdout adds LF); lines 101–105 retain pretty final samples and perform
  cleanup after the journal. State/error/exception string types have no complete
  serialized byte domain in this contract. This is an unproved upper bound, not
  a prediction that this exact server emits arbitrary-length strings or overruns.
- `r19/bounded.py:105` redirects child stdout/stderr directly into files;
  lines 136–158 poll/check afterward, including a 0.02-second sleep. Line 171
  writes terminal process metadata after those checks. Without a proved emission
  rate/write maximum, polling cannot provide a pre-write or overshoot bound.
- `r21/run-http-qualification.sh:96` runs cleanup, source/fixture/catalog/disk
  checks and final bookkeeping; lines 109–111 write after the cap calculation.
  Fixed timeouts, free-space floors and posthoc STOP do not bound these bytes.
- Temporary seed files are inside guarded TMPDIR (`r21` wrapper:31 and original
  driver:46). `tests/sot_fixtures.py:148`, :167, :195 and :200 write the five
  nominal package files; `test_context_memory_integration.py:123` explicitly
  passes that temporary root through synthetic settings. No additional staging
  copy is inferred. Live files and interrupted residue must be covered even
  though the historical final packet contains none.

Logging, migration/admin/Docker diagnostics, supervisor/stop streams, owner/result
copies, reconstruction/error text and outer transcripts are explicitly covered.
Empty historical stderr is not a zero maximum. R23's 1,281,810-byte wire size is
only its nominal synchronous model; real error/fallback/repeated-cancel coverage,
async transparency and restoration remain separate, unproved gates.

## Audit and actual verification scope

The audit is a closed, deliberately always-HOLD analysis checker. It rejects
missing/duplicate/unknown producers, unsupported proof promotion, caller numeric
limits for unproved entries, malformed types, duplicate/nonfinite JSON, changed
fingerprints and cap-exceeding models. Domain prose and witness structure are not
a semantic proof of every runtime path; source review supplies that distinction.
It must not be promoted into a general runtime admission validator.

Builder's final six unique memory controls passed in 0.003718 seconds with zero
failures/errors/skips; compile checks cover two files. Main's same six controls
passed in 0.003 seconds, not six additional unique tests; its two-file syntax/import
surface check passed. Main's audit exit 0 reproduces the stored analysis exactly.
I inspected these actual records but did not execute controls or import their code.
Initial author context/wording corrections and two author tool errors are retained.
Main's post-audit `store(undefined)` orchestration error is disclosed and did not
rerun the audit. Lint/typecheck, build and runtime/async/SQL/Docker/HTTP/native/
provider checks were NOT RUN; pure controls do not certify them.

R24-001 preservation, R24-002 producer analysis and R24-003 fail-closed controls
are accepted. The independent/Main evidence portion of R24-004 is accepted;
Contractor still owns final Verify/publication. Completion of four analysis
criteria does **not** close the whole-capture budget or authorize another run.

## One next decision

Request explicit approval for a finite **bounded-producer envelope** design,
covering every admitted writer, duplicated output, live temporary data and reserved
terminal/ownership/cleanup records. Whole-record admission must precede writes;
oversized/unsupported output must yield an explicit INCOMPLETE/STOP, never a
successful measurement. A limiter alone bounds an incomplete artifact, not lossless
complete evidence. Lossless unrestricted sinks, unchanged producers and a fixed
finite cap cannot all be guaranteed by this analysis. Narrowing the future
experimental retention/error representation requires authority and fidelity/
transparency proof; it is not granted or implemented in R24. No repeated analysis
loop, shorter polling interval, larger reserve, suppressed errors or new campaign
is recommended.

Only this new review was written. No prior evidence/source/publication was edited;
no runtime, external action, scratch copy, install or cleanup operation was used.
