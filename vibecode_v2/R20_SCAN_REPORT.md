# R20 Focused Scan Report

2026-10-09 · Builder · Vibecode Kit v6.2 · Source-read-only scan.

## Outcome and boundary

R19 failed during signed fixture bootstrap, not an HTTP operation: 0/1,600
observations, 1,600 missing, 0/16 evaluable cells. Its consumed campaign marker,
failure records, helpers and current product/tests must remain unchanged.
R20 should close the concrete seed environment prerequisite on fresh synthetic
data, without another campaign, engine DB, worker, API request or performance
allocation. No implementation or execution occurred in this scan.

## Stack, entry points and reusable seams

Backend Python 3.12, FastAPI, SQLAlchemy 2.0.43, asyncpg 0.30.0,
pydantic-settings 2.10.1, pytest 8.4.1, Alembic 1.16.4 and Ruff 0.12.9.
The relevant immutable dependency chain is:

`principal(factory, Role.ADMIN)` / `principal(factory)` →
`test_context_memory_integration.publish` →
`test_tip054_baseline_integration.synthetic_settings` →
real SOT stage/validate/publish → `ActionService.admit_capability`.

The original latency driver also uses a separate seed engine/factory. The
canonical runtime engine is independently configured as pool 5+5/pre-ping; its
construction need not perform a checkout. R20 can inspect those settings without
calling HTTP, executing a plan, initializing DBOS or contacting an engine DB.

Reuse the pinned R19 `bounded.py` directly, not a clone: evidence root
`/evidence/r19/r20_bootstrap_e1`, stage `pre`, labels other than `load`.
This supplies 120 seconds per child, one persisted shared 10-second cleanup
deadline, matching ownership and 10 MiB polled evidence cap. Reuse R18's
fixture/profile, safe-path and exact collection/XML helpers and source recipe.

## Source-backed finding

R19's clean environment contains `POSTGRES_DSN` but omits
`INTEGRATION_DATABASE_DSN`. The original baseline module captures
`DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN", "")` at import. Its
`synthetic_settings` explicitly passes that value to `Settings.postgres_dsn`.
The empty argument takes precedence over the otherwise valid environment value.
Actual `r19/http_e1/load.stderr.txt` follows this call chain and terminates on
empty-URL validation before publication and the HTTP loop. Principal SQL seeding
had already occurred; this is not a claim that no SQL ran.

The existing backend `conftest.py` only rejects a non-disposable integration
database when that variable is nonempty; absence passes that guard. Six R19
offline controls did not execute this transitive seed path. Positive bootstrap
proof, not another count-only environment assertion, is therefore needed.

## Preservation baseline

Current source recipe: sorted UTF-8 content-SHA/repository-relative-path lines.
Product: 204 files,
`b28e70d1905930fd517576b7df73edc6710cf4bae273f137da5e75ffd155c641`.
Tests: 192 files,
`5039c2a6a47fa1566f84b1acf766c5d212f731e6c9127aeec08576c7663fadc1`.
These are source facts, not serving image/build attestation.

Personally read and hashed:

- R19 source e5: `ebab6389b79674cd6a90110227ed02f9dce019c45b2ee299091ca337bebb21f4`.
- R19 evidence seal: `f99638aa32e497220eb6240f9e9147184bf93d350014ab40801c49e4d7e771cd`, declaring 220 pins.
- R19 final closure: `1956f317a591988d0b39343b25311c2154bb56f9601b4793046816b444357980`.
- Consumed marker: `bd5d22631a2613859f0611a98778e69c4fbbe207f4b44254a46ac19c7f3f5c9b`.
- R19 supervisor: `dacc9109adb89437817e58d5b537072f0063f1ce001b5151e5abc5c22fd376bb`.

R20 must recheck the declared pins and full current source inventories, not
inherit historical PASS as proof of a new bootstrap. It must additionally pin
R19 Verify/final review, which the earlier evidence seal deliberately excluded.
Do not change signed fixture timestamps, NOW (2026-07-31), source/reference
generation, helper assertions, factory logic, original tests or R19 bytes.

## Health, gaps and finite size

Main-attributed R19 pre: six controls PASS, exact XML, syntax/lint/format PASS.
Main-attributed final closure: owned R19 DBs absent, four original fixture
identities/profile/internal network unchanged and idle, host 82 GiB free.
This scan did not rerun those checks, import product or run tests/SQL/Docker.

P1 gap: absent/mismatched seed DSN must be rejected before runtime side effects;
the original imported global and actual Settings must be positively checked.
Separate historical host ownership errors remain preserved, with no general
root-cause inference.

Proposed addition is four small experiment files: a stdlib environment/source
contract, six grouped offline controls, two actual probe test functions, and a
guarded shell entry. No new supervisor or general framework. Exact new domain DB:
`rtr_tip054_r20_local_e1`. See the accompanying design for the eight proposed
test identities, ownership sequence and admission decisions.
