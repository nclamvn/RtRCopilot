# R27 owned broker — Builder Completion

Date: 2026-10-10. Role: Builder; Vibecode v6.2. Status: local implementation complete, whole-runtime qualification PARTIAL.

## Outcome and acceptance

| Criterion | Builder result | Evidence / boundary |
|---|---|---|
| B1 approved boundary | PASS locally | Fixed approved SCOPE/boundary hashes; drift rejects before broker-root creation. Platform transcript is separate disclosed audit, not zero or qualifying storage. |
| B2 sole writer and recovery | PASS locally | Real native sidecars and packet share prewrite accounting; complete records, overwrites, copies and deleted payload attempts remain charged. Strict recovery checks the live inventory and bounded ordered file-deletion history. |
| B3 source-connected controls | PASS within declared scope | Exact driver output/oracle blocks, full pure signed fixture, actual audit sink, safe shell/metadata expressions and the exact finite child; not twenty fully executed original runtime families. |
| B4 frozen check/preflight | PASS locally | Exact fourteen controls, explicit backend-config health, preservation and default-DENY CLI. Main/Reviewer verification remains independent. |

Original R27-001/002 remain PARTIAL; measured phases are NOT_RUN. No SLA repair or readiness inference follows these controls.

## Concrete implementation

`broker.py` owns packet/native writes; producers receive opaque logical paths and ports, never an exported physical path or file descriptor. Actual cached `open`/`os.open` calls on the facade reject before artifact I/O. This is a cooperative pinned-producer boundary, not a hostile same-UID or Python-introspection sandbox.

Before a destructive open, the broker admits the original whole payload against family/count, shared bytes and the complete predicted manifest. An unwritten overwrite/close is a charged empty operation. Physical write attempts plus packet framing are charged monotonically: deletion does not refund; overwritten/deleted raw attempts remain recoverable. The prepaid reserve is 16,988 bytes for bounded metadata/closure/controls; the final 90-byte marker is separately admitted before manifest I/O. No truncation, arbitrary chunk splitting or hash-to-PASS substitution is used.

Local limits are 32 file entries, 32 active handles, 32 active operations, 64 directories and 64 deletion records. They are admitted local domains, not a proof that the historical 63-file original runtime fits. Metadata is bounded to 16,384 bytes; the shared logical limit is 10,485,760 bytes, not physical filesystem-block accounting.

Finish rejects outstanding handles or child-operation tokens. Native/layout/raw/accounting checks precede seal creation. A committed epoch is immutable; misuse cannot change its bytes, and later external tampering is rejected by recovery rather than claimed automatically invalidated durably. Power-loss durability and hostile filesystem races are not proved.

Source bridges retain the original journal append-before-write/flush behavior, summary-file/stdout duplication, final JSON and exact known oracle `SystemExit(1)`. Integrity-valid SLA FAIL is distinct from capture failure; unknown exceptions, serialization/I/O/finalization failures remain sticky INCOMPLETE and preserve the original exception identity.

The full pure signed fixture produces five final files through six writes, including attestation overwrite. The full pure audit sink uses scoped rendered logging writes with restoration. No publish/admission SQL path is invoked. Safe shell copies/literals and R19 owner/process/deadline writer bodies are connected, but their effectful launcher is not executed.

The unchanged fixed child receives no broker root in argv/env/cwd and no broker descriptor. Concurrent bounded drains admit one whole EOF stdout record and one whole EOF stderr record, not read chunks. Cleanup uses one shared deadline and independently attempts joins after faults. Actual result metadata reports Linux/group authority false and observed child/task/EOF state. An operation token blocks premature seal and releases only after observed reap and all owned tasks complete. Controls assert no pending named owned tasks before event-loop shutdown. This is not universal stalled-spawn, descendant or Linux process-group enforcement.

## Actual checks and preserved attempts

Final `author-feedback.json`: command exit 0; fourteen unique controls PASS, zero failures/errors/skips, 2.994769 seconds; ten source/interface files compiled. Codec derivation plus AST/public-signature and real return-shape checks PASS. Scratch snapshots were empty before and after; source hashes were identical.

Main independently reports the same frozen fourteen controls PASS, wrapper exit 0, 5.463251 seconds, empty scratch before/after, the same 2,010 pins and unchanged source. Main's explicit backend-config strict/Ruff/format checks also pass all nine surfaces; its CLI independently exits 2/default DENY. These are attributed Main results in `main-feedback.json` and `main-health.json`, not additional identities or Builder-owned runs. Independent final review is pending.

`author-health-project.json`: explicit backend `pyproject.toml` configuration; strict mypy PASS on nine authored/interface surfaces, Ruff check PASS, format check PASS on nine. The byte-derived codec body is intentionally not strict/style body-audited: exactly four root/identity substitutions and its genuine typed interface are independently checked. No blanket ignores suppress debt.

Retained earlier records are not erased: core first 5 PASS/1 FAIL, subsequent overlapping six-control passes; peer e2 2 PASS/6 FAIL, e3 5 PASS/3 FAIL, e4/e7 eight-control passes, e6 7 PASS/1 FAIL and static failures with source snapshots. The first frozen fourteen-control runs passed tests but failed shared scratch equality during concurrent independent runs; both actual records remain. Initial default-config health was insufficient: Main's explicit backend check found 24 lint issues and seven formatting differences. Those actual results, first frozen thirteen files and format histories remain bound. Final results supersede, not discard, these attempts; overlaps are not additional test identities.

Main's directly pinned fresh 27 RequestConnection unit controls are a separate fake-engine/non-SQL witness, not 27 additional broker controls or real SQL lease proof.

## Frozen identity and preservation

Input binding: `f991ad0495ccd60abed4d85efc6d0dd2bf7f0395bff0d37e93547bc7b00a5db6`.

Candidate: `553542c994785a3882e416cef25830852cac9b47f3d4f743fb4343f6c263186f`.

Routing: `e543842de2e88905dbbb202788a760b9975b5633ab656e1e6f25d835e43122ab`.

Before/after: 2,010 pinned files / 15,420,190 bytes; 1,910 prior pins include the prior binding itself. All 204 product and 192 test/helper inventory entries match their prior digests. Old runtime candidate `3c3feb38…` and all sealed runtime/retention bytes are unchanged. Historical published mutable status/taskgraph hashes remain point-in-time metadata, not live assertions. Final feedback/preflight/this Completion are outside the source binding so Main may seal them independently without source mutation.

## Reproduction and next authority

From the repository root:

```sh
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=v2/apps/backend/src v2/apps/backend/.venv/bin/python -B v2/experiments/action_executor/r27/broker/checks.py
```

Exact three static commands are retained in `author-health-project.json` under `results[].command`; all explicitly select the backend configuration and nine named surfaces.

```sh
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=v2/apps/backend/src v2/apps/backend/.venv/bin/python -B v2/experiments/action_executor/r27/broker/preflight.py /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/experiments/action_executor/r27/broker/candidate.json
```

Final CLI exits 2 (expected HOLD): source/boundary match true; marker ABSENT and not written; effect dispatch false; unknown native writers CAPABILITY_DENY; runtime prerequisites NOT_RUN. Synthetic grant data cannot authorize dispatch. The platform-boundary approval is settled, not requested again.

Remaining concrete prerequisites are separately authorized live fixture/capacity/owned DB checks, Linux exact group/drain validation and source-connected original shell/admin/migration/analysis/unknown native outputs under this broker contract. They must be genuinely routed and tested before an original runtime campaign can qualify. No scope exclusion or empty family receipt supplies that proof. No new campaign, SQL/Docker/HTTP/network/Git/build/install or executor activation occurred; serving executor remains OFF, EXE-009 remains open after the preserved R21 SLA FAIL, broad candidate not ready and `.5` blocked.

All owned local test directories were automatically removed. No whole-project copy, new dependency install or new cache was created. Source/binding are frozen; no further Builder edits are planned.
