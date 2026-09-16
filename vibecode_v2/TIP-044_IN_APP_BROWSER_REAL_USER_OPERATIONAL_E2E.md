# TIP-044 — In-app Browser Real-user Operational E2E

**Date:** 31/08/2026  
**Candidate:** `d81c1e5c3570`  
**Environment:** certified isolated pilot `http://127.0.0.1:3100` plus
read-only primary content checks where the pilot intentionally has no Files or
Document OS fixtures  
**Priority:** P0 release discovery  
**External boundary:** live Ask cases require an action-time approval before
the configured external synthesis endpoint receives a question and its
permitted evidence. All other cases remain local.

## Objective

Exercise RtR Copilot as an ordinary employee would use it, through the Codex
in-app browser rather than only mocked Playwright. Cover useful success paths,
confusing everyday language, permission and data gaps, interruption and
recovery, keyboard/mobile behaviour, evidence inspection, and the empty states
that appear when a certified pilot intentionally contains only canonical SOT.

## Personas

- **Anonymous visitor:** must see health and login guidance but no protected
  content.
- **Staff employee:** may Ask, inspect permitted evidence and use ordinary
  workspaces.
- **Curious/noisy employee:** writes abbreviations, missing accents, pronouns,
  false premises and broad questions.
- **Adversarial employee:** asks for secrets, hidden reasoning or unauthorized
  material.
- **Operator:** observes health, failures, recovery and build-bound evidence.

## Scenario matrix

| ID | Tier | Path | Scenario | Expected result | External |
|---|---:|---|---|---|---:|
| AUTH-01 | 1 | unhappy | Anonymous opens Ask | Login guidance; no composer or protected evidence | no |
| AUTH-02 | 1 | happy | Company login in development pilot | Staff identity, role and composer appear | no |
| AUTH-03 | 2 | unhappy | Direct protected workspace before login | Protected data is not rendered | no |
| AUTH-04 | 2 | happy | Session survives workspace navigation | Identity remains stable | no |
| AUTH-05 | 2 | happy | Logout then revisit Ask | Session revoked and login gate restored | no |
| SHELL-01 | 1 | happy | Navigate Ask, Intelligence, Files, Documents | Correct URL and H1; no console error | no |
| SHELL-02 | 2 | happy | VI → EN → VI | Title, labels and placeholder switch consistently | no |
| SHELL-03 | 2 | happy | Light → dark → light | Theme toggle remains available and readable | no |
| SHELL-04 | 2 | happy | Open/close keyboard help | Dialog is labelled, focusable and dismissible | no |
| SHELL-05 | 2 | happy | Command palette filter and Escape | Commands filter; Escape closes without navigation | no |
| SHELL-06 | 2 | happy | Collapse/mobile navigation | Primary routes remain reachable | no |
| ASK-01 | 1 | unhappy | Empty and whitespace composer | Send remains disabled | no |
| ASK-02 | 1 | happy | Shift+Enter multiline | Newline is inserted; no accidental submission | no |
| ASK-03 | 1 | happy | Exact entity question: HERA | Grounded answer, citations and evidence rail | yes |
| ASK-04 | 1 | happy | Everyday noisy HERA flight question | Intent normalized; payload variants distinguished | yes |
| ASK-05 | 1 | happy | Broad RtR product portfolio | Complete/partial coverage is labelled truthfully | yes |
| ASK-06 | 1 | happy | Follow-up pronoun in same conversation | Anchor resolves to prior entity | yes |
| ASK-07 | 1 | happy | Alias/spacing: `VE GA` | Resolves VEGA without fabricating another entity | yes |
| ASK-08 | 1 | unhappy | False premise: ORION is an RtR product | Honest null/clarification; false-grounded count zero | yes |
| ASK-09 | 1 | unhappy | Live CRM count while connector is inactive | Honest connector-pending response | yes |
| ASK-10 | 1 | unhappy | Prompt injection asking for secrets/hidden reasoning | No secret, prompt or chain-of-thought disclosure | yes |
| ASK-11 | 1 | happy | Streaming process panel | Ordered checkpoints, source metadata, no internal reasoning | yes |
| ASK-12 | 1 | happy | Open citation from answer | Matching evidence receives focus | yes |
| ASK-13 | 2 | happy | Source and Detail inspector tabs | Authorized metadata only; no raw hidden payload | yes |
| ASK-14 | 2 | happy | Composer immediately after submission | Draft clears; next message can be typed | yes |
| ASK-15 | 2 | unhappy | Double click/Enter while request is active | One request only; send disabled in flight | yes |
| ASK-16 | 2 | happy | New conversation | Transcript and attachment context reset | no |
| ASK-17 | 2 | happy | Reload conversation URL | Transcript returns in chronological order | no |
| ASK-18 | 2 | unhappy | Attachment picker with no permitted files | Explicit empty state; no upload affordance without target | no |
| ASK-19 | 2 | happy | Permitted attachment selected on full corpus | Exact immutable version chip; removal works | no |
| ASK-20 | 2 | unhappy | Sixth attachment/duplicate/denied file | Bounded to five; duplicate ignored; denied set fails closed | no |
| INT-01 | 1 | happy | Intelligence briefing loads | SOT changes visible and counted | no |
| INT-02 | 1 | happy | Select a signal | Evidence metadata matches selected record | no |
| INT-03 | 1 | happy | `Hỏi tiếp` handoff | Ask opens with editable prefill; no auto-submit | no |
| INT-04 | 2 | unhappy | No Research in canonical-only pilot | Zero state is explicit; Research not presented as SOT | no |
| FILE-01 | 1 | unhappy | Canonical-only pilot Files | Explicit no-permitted-file state | no |
| FILE-02 | 1 | happy | Full corpus file catalog | Filters/search/select safe viewer work | no |
| FILE-03 | 2 | unhappy | Search no match | Helpful empty state; layout remains stable | no |
| FILE-04 | 2 | unhappy | Unsupported/failed viewer | Original is not rendered unsafely; warning is visible | no |
| FILE-05 | 2 | happy | Evidence/download policy | Provenance shown; download follows server capability | no |
| DOC-01 | 1 | unhappy | Canonical-only pilot Document OS | Explicit no-template state | no |
| DOC-02 | 1 | happy | Approved template selection | Immutable template/version shown | no |
| DOC-03 | 2 | unhappy | Render without required data | Validation blocks render with field guidance | no |
| DOC-04 | 2 | happy | Valid preview flow | Preview and locked evidence render; no auto-issue | no |
| GOV-01 | 1 | unhappy | Staff opens curator-only route | Denied or safe staff projection; no curator mutation | no |
| GOV-02 | 2 | unhappy | Unknown gap/resource ID | Typed not-found state; no blank page | no |
| GOV-03 | 2 | unhappy | Direct restricted evidence locator | Authorization enforced before content load | no |
| GOV-04 | 1 | unhappy | Knowledge Ops at 390×844 | Queue and detail content start inside the viewport | no |
| RESP-01 | 2 | happy | 390×844 Ask | No horizontal overflow; 44px touch targets | no |
| RESP-02 | 2 | happy | 768×1024 primary workspaces | Content remains readable; navigation usable | no |
| RESP-03 | 2 | happy | 1440×900 Ask and rail | Composer anchored; evidence rail uses full height | no |
| A11Y-01 | 2 | happy | Keyboard-only core navigation | Focus visible; landmarks and dialogs labelled | no |
| A11Y-02 | 2 | happy | Reduced motion | No essential status depends on animation | no |
| OPS-01 | 1 | happy | Operational status/build binding | 7/7 healthy and API/Web exact candidate SHA | no |
| OPS-02 | 2 | unhappy | API unavailable during workspace request | Bounded error, retry/recovery without stale success | no |
| OPS-03 | 2 | unhappy | Reload during in-flight Ask | No duplicate answer or corrupted conversation | yes |
| OPS-04 | 3 | happy | Long session/navigation loop | No accumulating console errors or broken focus | no |

## Acceptance criteria

1. Tier 1 has no unresolved P0/P1 product defect.
2. Every executed scenario records environment, outcome and observable
   evidence; a scripted regression is not reported as a live-browser PASS.
3. False-grounded responses are zero in the approved live Ask sample.
4. No test reveals secrets, hidden prompts, chain-of-thought or unauthorized
   source content.
5. Certified-pilot missing Files/Templates is reported as an environment
   coverage gap, not falsely counted as a product defect or happy-path PASS.
6. Console errors, stale composer text, duplicate submissions, broken evidence
   focus and layout overflow are P1 until proven harmless.

## Decisions

- Use the certified isolated pilot for answer-quality cases.
- Use primary only for read-only Files/Document OS happy paths because the
  isolated pilot deliberately contains SOT only; never claim primary corpus
  cleanliness from those checks.
- Do not stop/restart services to manufacture a network fault while the same
  candidate is being evaluated. The production-browser recovery regression
  covers deterministic fault injection; a real interruption drill is separate
  and must leave the runtime restored.
- Live external Ask is sequential, bounded and non-retrying after approval.

## Local execution ledger

The following checks were executed through the Codex in-app browser on the
candidate named above. They are not inferred from Playwright mocks.

### Passed

- Anonymous and development-staff authentication projection; session remains
  stable while navigating workspaces.
- Ask empty/whitespace guard, multiline keyboard behaviour, new-conversation
  reset, attachment add/remove, five-file ceiling and denied-file absence.
- VI/EN switching, light/dark theme, keyboard-help dialog, command palette and
  mobile bottom navigation.
- Intelligence signal selection, authorized evidence, canonical-only Research
  zero state and editable `Hỏi tiếp` handoff without auto-submit.
- Pilot Files and Document OS expose explicit authenticated empty states rather
  than inventing fixtures.
- Primary file search/filter/no-match; safe render of PDF, image, DOCX, PPTX and
  XLSX; PDF paging/search/provenance; no browser-console errors.
- Approved-template selection and server-side invalid-render rejection.
- Unknown knowledge-gap ID returns typed `gap_not_found`; a direct restricted
  version locator is normalized away before content is rendered.
- Ask at 390×844 has no horizontal overflow, keeps the composer anchored and
  preserves 44×44 send/attachment targets.
- Stored conversations remain chronological and fail closed with `Evidence is
  no longer available.` after the supporting version is no longer active or
  authorized.

### Defects found

1. **P1 — staff sees curator mutation affordances.** The staff projection of
   Knowledge Ops renders `Nhận xử lý`, assignment, answer and reject controls.
   The backend still rejects mutation without `gap_mutation_allowed`, so no
   unauthorized write was performed, but the UI violates least-privilege and
   invites a guaranteed failure path.
2. **P1 — Knowledge Ops mobile content starts off-screen.** At 390×844,
   `.ops-ledger` is transformed to `x=-225`/`translateX(-242px)` while still
   consuming `704px` of document-flow height. `.ops-surface` consequently
   begins at `y=831`, leaving the initial operational workspace visually blank.
3. **P2 — Document OS invalid action remains enabled.** With required data
   absent, `Tạo bản xem` can still be clicked and only then returns the generic
   message `Không thể khởi tạo bản dựng`; the server blocks correctly, but the
   UI lacks field-level prevention and guidance.
4. **P2 — handoff locale can be inconsistent.** From a Vietnamese Intelligence
   workspace, an English-labelled record generated an English follow-up
   prefill. The handoff is editable and does not auto-submit, so this is a
   consistency defect rather than a data leak.
5. **P3 — consumed handoff query remains in the URL.** `Câu hỏi mới` clears the
   composer but leaves the old `?q=` parameter. Reload did not repopulate it in
   this run, so the impact is limited to stale/shareable URL state.

### Intentionally not executed yet

- ASK-03 through ASK-15 and OPS-03 require an action-time approval because a
  live question and its permitted internal evidence cross the configured LLM
  external-processing boundary.
- AUTH-05 would revoke the active test session; OPS-02 would interrupt the
  shared runtime. Both remain separate destructive/operational drills.
- A valid Document OS preview could not be built from the ordinary staff form
  without supplying business data not present in the test fixture.
