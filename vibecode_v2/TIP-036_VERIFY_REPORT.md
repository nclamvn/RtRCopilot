# VERIFY REPORT — TIP-036

**Date:** 15/08/2026

**Scope:** Ask-to-Artifact Orchestration

**External processing:** none

## Requirement coverage

| Metric | Result |
|---|---:|
| Requirements | 12 |
| Implemented | 12 |
| Deferred implementation | 0 |
| Coverage | 100% |

## Trust-boundary verification

| Gate | Result |
|---|---:|
| Ordinary question does not become an action | PASS |
| Bare create verb requests clarification | PASS |
| Draft/retired/denied template excluded | PASS |
| Independent `view` and `render` authorization | PASS |
| Current approved version only | PASS |
| Candidate count bounded to three | PASS |
| Explicit user confirmation required | PASS |
| No prompt/evidence in browser URL or storage | PASS |
| Planner failure does not block Ask | PASS |
| No automatic render/approval/issuance/publication | PASS |

## Technical verification

| Gate | Result |
|---|---:|
| Focused backend artifact tests | 4 PASS |
| TIP-024 adapter determinism | PASS in combined run |
| Ruff | PASS |
| mypy | PASS — 8 source files, 0 issues |
| Web unit/component/contract | 199/199 PASS |
| TypeScript | PASS |
| ESLint | PASS |
| Next.js production build | PASS |
| `git diff --check` | PASS |
| Canonical bootstrap first run | 4 approved templates · 32 ACL grants |
| Canonical bootstrap second run | 4 idempotent templates · 0 ACL grants |
| Live staff template API | 4 canonical templates |
| Live planner API | document/report/spreadsheet routing PASS |
| Live browser handoff | Correct version selected; required fields rendered |
| Primary runtime | 7/7 containers healthy · `operational` |

## Environment-specific test note

The combined macOS backend document test run produced 22 passes and one known
environment-only PDF extraction failure because `/usr/share/fonts/truetype/
dejavu/DejaVuSans.ttf` is absent from the temporary host virtualenv.  The
production-shaped backend image installs DejaVu and Be Vietnam Pro fonts, and
the rebuilt API container is healthy.  This is the same host-only font condition
already recorded before TIP-036; the new artifact planner tests all pass.

The broader backend suite was not reclassified as fully green by this report:
its earlier two host-only conditions (font and Linux `libseccomp`) remain
explicit rather than being hidden.  No affected code path was changed by
TIP-036.

## Runtime consistency

An intermediate API-only rebuild correctly triggered `version_mismatch` in the
Web status gate.  API, Worker and Web were then rebuilt together from the same
working tree.  Final state is `operational`, `answer_quality=evidence_only`, and
all seven primary containers are healthy.  Because the worktree is not yet
committed, this is a local verification build, not a release candidate.

## Overall status

**TIP-036 local implementation and verification: PASS.**

Commit/push, immutable candidate build binding, pilot recertification and
production work are outside this TIP and were not claimed.
