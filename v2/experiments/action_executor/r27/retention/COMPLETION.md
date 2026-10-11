# R27 retention continuation — Builder Completion

2026-10-10 · PARTIAL · same consolidated R27 package, no new milestone.

## Implemented and frozen

The isolated finite-retention contract is approved by the user decision and
source-pinned SCOPE.md. Historical R25 proposal labels remain unchanged.
Measurement/campaign admission remains HOLD.

New continuation files implement real native file routing, packet retention,
scoped restoring Python file/directory/stream/logger hooks, strict sidecar recovery,
and joined finite raw pipes. Every packet frame and physical copy/write is charged
before I/O under one 10 MiB cap; overwrite/deletion/failure never refunds charge.
Reserve is 340 bytes closure metadata + 264 packet controls + 16,384 native
metadata bytes. The old packet-only maximum does not prove combined fit.

Actual connections tested: exact source journal retain, summary/report/write/print
and final-samples producer blocks; full pure signed-fixture build_package function
(five files, six writes including attestation overwrite); full AuditEvent and
StructuredAuditSink.emit with real rendered logging; unchanged full RequestConnection
constructor/join_terminal with a nonconnecting engine and real async cancellation.
No original request driver, publication/staging/SQL or physical lease was executed.

Each original Python producer write/emit is admitted whole, not split to fit.
Unframed fixed-child pipes drain concurrently as whole raw streams, including
0xff bytes. Packet and real sidecar copies are both charged. Cached file/stream
operations require the creator thread and active context; closed/stale operations
fail sticky. Explicit finite-child packet routing is creator-thread-only.

Strict recovery checks source/epoch identity, bound metadata, complete packet
grammar, exact native inventory/bytes and shared aggregate. Bad files are bounded
before reading. Source/serialization/model/write/flush/cleanup failures remain
INCOMPLETE. The exact original oracle SystemExit(1), identified by traceback
code/line/object, propagates unchanged while a completely retained SLA FAIL can
remain integrity-valid. Arbitrary Exit(1) and finalizer faults are not exempt;
recorder cleanup does not mask the primary exception.

## Actual results and reproducible command

Corrected Builder execution: eight unique grouped controls PASS in 1.276 seconds;
zero failures/errors/skips; seven compile checks PASS; sandbox lists empty.
Controls include 1,600 static output-producer rows, full fixture/audit calls,
shared-budget saturation/overwrite/copies, cached-endpoint ownership negatives,
enter/logger-cache restoration, corruption/oversized-reader negatives and repeated
cancellation of real finite children. Static rows are not HTTP observations.

```sh
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/backend/src \
  v2/apps/backend/.venv/bin/python -B v2/experiments/action_executor/r27/retention/checks.py
```

Main independently reports the same eight controls PASS in 1.299927 seconds.
Main's separate unchanged full-class lifecycle unit run passed 27 cases; this is
attributed evidence, not a Builder run or SQL proof.

Before/after matched 1,868 pins / 14,165,189 bytes, including the 1,840-pin prior
graph and complete 204 product / 192 test inventories. Old R27 source, binding,
reports and prior linked evidence are unchanged. Source hashes before/after match.

Ruff check PASS / format PASS on six newly authored modules; preserved derived
adapter was not mechanically reformatted. Corrected strict mypy FAILED with
246 errors in five files (six checked): 75 untyped definitions, 143 untyped calls,
12 union, 4 miscellaneous, 1 attribute, 5 argument, 1 assignment, 1 method assignment,
4 variable annotations. This is P2 static debt, not zero or a waived gate.
No build, SQL, Docker, HTTP/load, provider, external company-data processing,
executor activation, Git or dependency restore was performed by Builder.
Main restored existing locked venv dependencies separately.

## Preserved failures and cleanup

One initial pre-test derivation STOP found an extra trailing newline; no control
or child had run. That binding/failure remains pinned. The first tested version
passed eight controls but independent review found a material cached-owner gap and
oracle-integrity conflation. Its three changed source files, binding, feedback and
226-error type result are preserved; corrected results do not erase those findings.
The corrected run exercises the same eight groups, not extra campaign attempts.

Owned sandboxes were automatically removed. The type command's newly created
313-file / 14,385,540-byte root mypy cache was explicitly inspected and removed;
future corrected checks use /dev/null cache. No project copy or new environment.

## Coverage, health and handoff

R27-001 and R27-002 are PARTIAL: supported local routing/fidelity work, but complete
original-family exclusivity remains unproved. R27-003/004 are PENDING: no measured
diagnosis, repair or performance qualification. R27-005 is PARTIAL pending Main's
consolidated Verify/publication. Fully completed package criteria: 0 of 5.

routing.json maps all twenty families by actual invocation, not twenty endpoint
receipts. Native/cached descriptors, temporary writers outside registered roots,
Bash/Docker/admin/migration/supervisor and outer streams remain explicit HOLD.
They block measurement; no further toy-model milestone is proposed.
R21 SLA FAILED/P1, EXE-009 OPEN/P1, candidate NOT_READY, serving executor OFF and
TIP-054.5 BLOCKED remain unchanged.

Final binding: 0b5f74f36df0fb3d535e2b38bbecefef694a047cb29f2a734259d9d2c2a8af36.
Corrected feedback: 30e774b01a3254049c0d19b1f4c2c4cdb61b9279e5002e4005c57ab3e737bee2.
Corrected health: a1341d9d2c6765ebb145fadc8a82a95eb6cd65eba0796c193b90180d4ad845df.
All bound source is frozen; only this handoff report was added after verification.

