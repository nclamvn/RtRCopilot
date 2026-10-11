# R27 PRE contract — independent review

2026-10-10 · Vibecode Kit v6.2 · source/evidence Reviewer

**Verdict: E1–E4 scoped local source/control outcomes ACCEPTED (4/4). Full R27 remains PARTIAL / NOT_READY; original PRE remains DENY / NOT_RUN.** No blocking defect found in the supported diagnostic path. This review does not adopt a scratch classification, raise capacity, authorize an effectful stage or close EXE-009.

## Frozen identity and method

Reviewed the complete SCOPE, four modules, candidate/manifest, original R21 producer bodies, relevant tempfile/pytest source, Completion and actual Author/Main evidence. Reviewer performed only source/AST, JSON, hash and independent stdlib arithmetic checks: no implementation/helper imports, test runs, subprocess workloads, SQL, Docker, Git or external calls. Only this new report was written; old reports and artifacts remain untouched.

- Binding: `1e7dfca6f0dc4bb89f80d94b4926ff28ae48faf35e7bb7da9241e5218bc1c770`.
- Candidate: `09eb6fd832c0eb6a23068c9ac873ca450ddba887aa24a9167402fc693e183d4d`.
- Manifest: `3b99972f22fd0533a563da6d1a8ca74961b38ce0729bab83ec1f501fa48d3d63`.
- Completion: `c3e245f68273e5a6bd79e03d59de3cad2560eacf50bed4d43afe59fe6c295b15`.

## Acceptance findings

| Scope | Independent finding |
|---|---|
| E1 | Original `test_r21_offline.py:51–85,206–240` really emits whole payloads, not measurement append calls. Independent literal/AST reconstruction matches all 27 full/four/one payload hashes: full JSON/JSONL 235,440/233,840 B; four 582/578 B; one 153/152 B. Corruption lifecycle is 35 writes, 733,169 B lifetime payload, nine names and 4,050 B final live content. Six-method clean-success lower bound is 43 writes, 14 lifetime scratch files and six temporary roots. Launcher 125 files/75 source-cap producer records plus closure is only a nominal lower bound; 125+14=139 already exceeds32, without proving all plugin/failure writers. |
| E2 | `bridge.py:56,161,222` guards source identities before loading the unchanged stdlib-only chain and compiling exact `rows`, `write_packet` and `marker` nodes. No JSONL slicing, lossy replacement or native path export. `test_pre_contract.py:58` checks natural full/four rejection at the original whole journal write (233,840/578 >512 B), after four admitted prefix writes; ephemeral full rejects JSON (235,440 >65,536 B), after three. The rejected artifact is absent, admitted raw prefix survives, rejected charge is unchanged, original traceback/first exception is retained and finish cannot seal. |
| E2 continued | `test_pre_contract.py:91,127` exercises the existing one-row parameter through genuine unchanged OwnedBroker/HostPort: raw fidelity, recovery, overwrite/delete without refund, exhausted-copy rejection before overwrite, native/source/storage faults and sticky identity. A valid one-row diagnostic capture is not full PRE or measured SLA success. MemoryPreview quantifies source serialization only; it is not broker/storage qualification. |
| E3 | `admission.py:149` validates pinned sources and unconditionally raises before root, child or marker creation. It has no approval/grant branch. Candidate count, mapping, boolean and request dictionaries cannot authorize dispatch; unknown/missing producers remain DENY. CLI evidence actually exits2 with source_matches=true, effects NOT_RUN. |
| E4 | Exact 28 outer identities match source AST: unchanged23 plus new5. Main and Author actual results overlap; they are not56 tests. Source, prior graph, inventories and owned scratch agree before/after. Project-config health is clean for the four new modules. Contractor publication remains its own downstream responsibility. |

Original cap (`r19/qualification.py:177–185`, polling in `bounded.py:131–148`) sums **surviving** recursive file sizes, not lifetime attempted copies. R21 launcher sets TMPDIR and basetemp inside evidence (`run-http-qualification.sh:31,165–167`); cleanup/overwrite can disappear before a poll. Strengthened prewrite packet+physical/no-refund accounting is intentionally stricter, not equivalent. The given-basetemp pytest branch bypasses the ordinary session cleanup-lock path; numbered tmp_path still creates a current symlink. Stdlib tempfile first resolution can write/unlink a four-byte probe and fall back to other native directories. `synthetic_settings` construction itself is not a payload writer. None of these unconnected routes becomes qualified by the logical diagnostic facade.

## Actual evidence and preservation

Main `main-feedback.json` (chunk `125f9d`): **28 PASS**, wrapper0, zero failures/errors/skips, 5.77587450001738 s, compile4, source/preservation equality and scratch `[] → []`. Author: same28 PASS, 5.919770709006116 s. Two disabled-async-plugin configuration warnings are preserved. Earlier four type errors/seven E501 findings and exact source history remain retained; no prior failure is presented as same-byte success.

Main `main-health.json`: strict4 exit0, Ruff exit0, format4 exit0. `main-preflight.json`: exit2/DENY, not a successful effectful PRE. Evidence hashes respectively:

- Feedback: `20f11cc527622a08b2772cd8b9d885dea7291faa7141696a71e9cfc4b6217ada`.
- Health: `71aa68ea47a3ad1ede791fbde7b8c06b784a11cbb7406aad86fe86f500ad87e8`.
- Preflight: `c3b848e44638bd588a8411f71971819a1308c0f4b7b0f9a6c257bd956a66f923`.

Reviewer independently rehashed **2,249 repository pins /17,458,659 B**, including prior2,218 /17,154,176 B; all matched. New43 direct pins/one linked anchor and three new external interface pins match. Full product204/test192 sets and digests remain `b28e70d…` / `5039c2a…`; Main's unchanged HEAD witness is attributed, not a Reviewer Git run. Old broker/real_path/runtime_closure sources and sealed reviews remain intact. Current actual broker seals still use their frozen real_path witnesses; this new external binding separately covers the diagnostic additions.

## Remaining decision, not an adopted fix

Current32/PRE32, twenty families, shared10 MiB, metadata16 KiB, whole records and no refunds remain operative. Earlier96/PRE64 is insufficient and NOT_ADOPTED. Genuine tempfile/rmtree, native pytest basetemp/symlink, fake-shell drops, arbitrary warning/error streams and full Docker/Linux/SQL/dependency paths remain unqualified. There is no complete PRE byte/file/range/metadata upper bound or dispatch authority.

Recommend one cohesive material decision: a **stage-specific PRE synthetic-input variant inside the same shared10 MiB/no-refund boundary**, with source-derived whole-write/file/metadata bounds and ownership for every deleted/native scratch route. Keep synthetic negative-test inputs distinct from real measurements; no uncapped scratch plane, silent exclusion or count-only grant. This proposal is not adopted by this review. R21 SLA remains FAILED/P1, EXE-009 OPEN/P1, executor OFF and TIP-054.5 BLOCKED.
