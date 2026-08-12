# TIP-033 — Latency Tail & Streaming UX

**Status:** Implemented · local verification PASS · bounded live recertification pending explicit export approval
**Date:** 2026-08-12
**Owner:** RtR Copilot
**Method:** Vibecode Kit v6.1 — Contractor / Builder / Homeowner

## 1. Problem statement

TIP-032 restored correctness and bounded external recertification, but exposed a
material latency tail: the five approved cases reached **p95 45,085.794 ms**.
The two governed product/dossier requests dominated that tail. The Ask API
already uses SSE, yet it streams only coarse checkpoints and the main transcript
still looks almost idle while synthesis is running.

The product must become perceptibly responsive without weakening enterprise
trust. Rendering raw LLM tokens before citation, coverage and lineage checks is
therefore explicitly out of scope: fast-looking misinformation is not a latency
improvement.

## 2. Decision

Adopt **evidence-first streaming** plus an **intent-aware fast synthesis path**:

1. Stream bounded checkpoints, monotonic sequence, per-stage duration and
   authorized source metadata.
2. Mark the first useful milestone when permitted sources are available and the
   evidence-ready milestone only after policy, relevance and lineage checks.
3. Keep answer text buffered until deterministic grounding and persistence pass.
4. Use low reasoning for routine definition, lookup and governed enumeration;
   retain the configured high-effort route for comparison, procedure and
   analysis. Output schema, evidence-only prompt and all grounding gates remain
   unchanged.
5. Right-size output headroom for dossiers and catalogs; do not truncate a
   required governed member or supported profile facet.

## 3. Trust boundary

- SSE may contain fixed checkpoint codes, durations, counts and metadata for
  evidence already authorized for the caller.
- SSE must never contain prompts, hidden reasoning, retrieved snippets, draft
  answer tokens, denied-record counts or secrets.
- `sources_ready` means candidates were retrieved and authorized; it does not
  claim that they will be cited.
- `evidence_ready` means policy, relevance, coverage preflight and current
  lineage passed; it is still not a final answer.
- Only the existing `result` event may contain answer text and citations.

## 4. Work packages

### Contractor

- Freeze the TIP-032 five-case quality oracle and latency baseline.
- Define first-feedback, first-useful and final-result SLOs.
- Preserve external-processing approval as a mandatory live-test gate.

### Builder

- Add typed SSE sequence, milestone and stage-duration metadata.
- Replace free-form progress detail with fixed, content-free checkpoint codes.
- Add a restrained transcript thinking state with source readiness and elapsed
  time; keep the right rail as the detailed process/source ledger.
- Add a routine-task reasoning lane and bounded output policy to the OpenAI
  structured answer client.
- Add regression tests for transport ordering, parser strictness, reduced motion,
  source disclosure and the no-draft-token boundary.
- Add a TIP-033 recertification wrapper whose exact case set cannot be widened by
  environment override.

### Homeowner

- Compare live results with TIP-032 for all five cases.
- Reject any release with false-grounded output, missing governed items,
  citation regression or p95 above the final-result gate.
- Visually inspect desktop, narrow desktop and mobile Ask states.

## 5. Acceptance criteria

| ID | Gate |
|---|---|
| AC-01 | First SSE checkpoint is emitted before provider answer synthesis and transport order is monotonic. |
| AC-02 | Heartbeat cadence remains at most 1.5 seconds while work is active. |
| AC-03 | Progress events expose only the typed allowlist; no prompt, snippet, draft token or CoT. |
| AC-04 | `sources_ready` is emitted only with authorized source metadata; `evidence_ready` only after context policy and current-lineage checks. |
| AC-05 | Main transcript shows a legible live state, elapsed time and verified-source readiness without fake answer skeletons. |
| AC-06 | Motion is disabled under `prefers-reduced-motion`; status remains available through an ARIA live region. |
| AC-07 | Routine definition/lookup/enumeration uses the configurable low-reasoning lane; complex reasoning retains the quality-primary setting. |
| AC-08 | Structured schema, citation requirements, semantic-review escalation and deterministic grounding remain unchanged. |
| AC-09 | Exact live set OPS-010, SYS-007, MTH-004, PRD-001, PRD-023: 5/5 pass, false-grounded 0, citation accuracy 1.0. |
| AC-10 | Exact live set final p95 ≤ 25,000 ms and no individual case exceeds 45,000 ms. |
| AC-11 | Backend unit/integration, web unit/browser/a11y/responsive, Ruff, mypy, ESLint, TypeScript and production build pass. |
| AC-12 | Live recertification cannot run without explicit approval for the immutable five-case export. |

## 6. Rollback

- Set `RAG_ANSWER_ROUTINE_REASONING_EFFORT=medium` to restore the TIP-032
  synthesis lane without reverting trust or UI work.
- The new progress fields are additive and optional to clients; old clients keep
  consuming stage/status/elapsed/source metadata.
- Remove the transcript live-state component independently; API `result` remains
  backwards compatible.

## 7. Evidence required for completion

- Unit and integration outputs.
- Browser screenshots for active retrieval and active synthesis.
- Exact bounded external report, produced only after explicit approval.
- Runtime build identity and container health.
- Completion and Verify reports cross-linked to immutable artifacts.

## 8. Current gate status

- AC-01–AC-08, AC-11 and AC-12: **PASS** on the local production build.
- AC-09 and AC-10: **PENDING**, because TIP-032 approval was purpose-bound and
  does not silently authorize a new TIP-033 transmission. The wrapper refuses
  to run unless `TIP033_APPROVE_EXTERNAL=1` is supplied for the immutable five
  cases.
- No live prompt, evidence or credential was written to a TIP-033 report during
  local verification.
