# TIP-044 — Completion Report

**Date:** 31/08/2026  
**Candidate:** `d81c1e5c3570`  
**Method:** Codex in-app browser, ordinary-user interaction, desktop and
390×844 mobile viewport  
**Status:** `PARTIAL — LOCAL CAMPAIGN COMPLETE, EXTERNAL ASK PENDING`

## Delivered

- A 57-scenario operational E2E matrix covering anonymous/staff personas,
  everyday and adversarial Ask behaviour, navigation, Files, Document OS,
  governance, responsive/accessibility and recovery paths.
- Live browser execution against certified isolated pilot `:3100`, with
  read-only fixture-dependent checks against primary `:3000` clearly separated.
- Happy-path validation for navigation, authenticated empty states,
  intelligence handoff, safe multi-format viewers, attachment limits and
  permission enforcement.
- Unhappy-path validation for empty input, no-match search, missing templates,
  invalid document render, unknown gap IDs and direct restricted locators.
- Reproduction evidence and likely layout mechanism for two P1 defects, plus
  two P2 and one P3 usability/consistency defects.

## Material findings

| Severity | Finding | Security/data outcome |
|---|---|---|
| P1 | Staff sees curator-only mutation controls | Backend still denies; no mutation attempted |
| P1 | Knowledge Ops content initially blank at 390×844 | No data loss; primary mobile workflow unusable |
| P2 | Invalid Document OS build remains clickable | Server rejects; no artifact created |
| P2 | Intelligence follow-up prefill may ignore VI locale | Editable; no auto-submit |
| P3 | Cleared handoff leaves stale `?q=` in URL | Reload did not restore the old text |

## External-processing boundary

No live Ask request was submitted during the local campaign, therefore no new
question or evidence was sent to an external LLM by TIP-044 so far. Eight
bounded cases are prepared and await the required action-time confirmation.

## Completion verdict

The scenario design and local/read-only browser campaign are complete. TIP-044
is not globally complete until the approved Ask sample runs and the two P1
defects are remediated and rechecked. The current candidate is **not a clean
company-wide release candidate** on mobile/governance UX grounds.
