# TIP-005 · Builder Completion Report

- **Builder result:** DONE · 18/18 AC reported PASS at foundation scope
- **Reported at:** 2026-07-30
- **Independent verification:** VERIFIED · READY

## Reported technical evidence

| Gate | Result |
|---|---:|
| Backend unit/API tests | 133 passed · 16 skipped |
| PostgreSQL/MinIO integration | 16/16 |
| Web tests | 1/1 |
| Ruff | PASS |
| Mypy strict | PASS · 47 source files |
| Policy parity | 48 scenarios |
| Runtime database denials | 9 |
| Supported input types | 14 |
| Required rendition outputs | 31/31 with checksums |
| Migrations | 5 revisions · 5 fixtures |
| Live services | 7/7 healthy |
| Pinned unauthenticated Trivy image gate | 0 HIGH/CRITICAL · Debian 0 · Python 0 |

## Delivered foundation

- Additive `0005` migration for upload sessions, durable ingestion jobs/outbox and
  rendition provenance/quality.
- Authorized streaming quarantine with bounded configuration and UUID object keys.
- Magic-byte and structural validation, safe OOXML inspection and fail-closed ClamAV.
- PostgreSQL leases, retry/idempotency and outbox-based delivery.
- Deterministic document extraction, safe preview outputs and real FFmpeg media
  normalization.
- Typed upload/status/retry/viewer/content APIs with request-time authorization.
- Immutable provenance, locator/quality schemas, redacted errors, audit and metrics.
- Offline Tesseract OCR with rotation/geometry/confidence provenance and offline Vosk
  transcript JSON/WebVTT with time bounds.
- Private/no-egress defaults and a non-root, capability-dropped, seccomp-enforced
  child-process sandbox.
- Effective ACL lineage from source/parent through document, version and rendition;
  `private_context` is owner-only unless a non-owner has an active action-specific
  allow, and any active deny wins without an admin bypass.

## Builder format and service evidence

- Fourteen allowlisted inputs produced 31 required output artifacts:
  eight image, eleven PDF/Office and twelve media outputs.
- Real ClamAV reported clean input as clean and the runtime-generated scanner fixture
  as infected.
- Media sandbox produced required outputs for WAV, MP3, M4A, OGG, MP4 and WebM.
- Real local Tesseract OCR and Vosk transcription execute without data egress.
  Optional engine failure remains non-fatal and produces explicit
  `*_unavailable` warnings.
- Vosk model `vosk-model-small-en-us-0.15` is checksum-pinned, licensed Apache-2.0
  and recorded in OCI labels; its installed footprint is 68 MB.

## Declared deviations

- Docker Scout remains intentionally unused because it requires authentication.
  The required vulnerability threshold is instead enforced by a digest-pinned,
  unauthenticated Trivy scan of the saved local image with no Docker socket mount.
- OCR and transcription are intentionally private/offline engines; no external
  provider or data egress is used.

This records Builder evidence only. Independent QA controls READY/NOT READY.
