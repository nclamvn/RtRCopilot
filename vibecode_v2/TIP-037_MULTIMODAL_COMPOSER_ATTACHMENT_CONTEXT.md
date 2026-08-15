# TIP-037 — Multimodal Composer & Attachment-to-Context

**Date:** 15/08/2026
**Status:** `COMPLETE`
**Base source:** `7644563096c91942cb8fe295fa18804099685ccd` plus TIP-036
**Owner:** Homeowner — Nguyễn Cảnh Lâm
**Method:** Vibecode Kit v6.1

## 1. Objective

Turn the existing single-file Ask scope into a useful, governed multimodal
composer. An authenticated employee can attach several authorized company
files—or upload a new image, PDF, Office document, video or audio file—and ask
one grounded question across the exact immutable versions.

This TIP reuses the TIP-008 File Workspace ingestion and viewer pipeline. It
does not create a browser-only parser, a second upload store, or a direct
raw-file path to the answer LLM.

## 2. Non-negotiable trust boundary

1. Every attachment becomes Ask context only after the server has accepted its
   upload, malware/DLP/format checks and rendition processing.
2. Ask receives immutable `document_version` UUIDs, never a filename, local
   path, blob URL or client-supplied extracted text as authority.
3. Retrieval independently evaluates current `view` policy for every version
   at question time. If any selected version is missing, revoked or above the
   requested classification ceiling, the attachment scope fails closed.
4. Only chunks from the selected versions may enter the answer evidence set.
5. The answer remains citation-bound; file evidence remains in the PRIVATE
   plane and is re-authorized when a conversation is reopened.
6. No attachment content is persisted in URL, localStorage or sessionStorage.
7. The context set is bounded to five unique versions and uses the existing
   global candidate/evidence byte budgets.

## 3. Product behaviour

### 3.1 Composer

- A compact attachment control lives in the existing bottom composer.
- The employee may select multiple files from the ACL-filtered catalog.
- When an upload destination is authorized, the same surface can upload one
  supported file at a time through the existing Files API.
- Upload progress is explicit. A processing upload cannot be submitted as
  context; rejection/failure is shown and never silently ignored.
- Ready attachments appear as small monochrome context chips with media kind,
  filename and an accessible remove action.
- Duplicate versions are ignored and the sixth selection is rejected with a
  visible bounded-limit message.

### 3.2 Ask contract

- Legacy `filters.version_id` stays accepted for compatibility.
- New `filters.version_ids` accepts one to five unique UUIDs.
- `source_key`, `version_id` and `version_ids` are mutually exclusive evidence
  boundaries.
- Query intelligence disables the enterprise-wide entity dossier for either
  form of explicit file scope.

### 3.3 Retrieval

- All selected versions are authorized before any file content query.
- One bounded vectorization and one bounded content query search the union.
- Ranking and evidence-byte limits apply globally, not once per attachment.
- Citation metadata retains the precise document version and source filename.

## 4. Explicitly out of scope

- Direct vision/audio inference over raw bytes.
- OCR/transcription in the browser.
- Connector activation, Google Workspace, Slack/native chat or ERP writeback.
- Automatic publication, approval or external delivery.
- Production deployment and production identity/secrets configuration.

## 5. Acceptance criteria

- **AC-01:** one-file legacy requests behave unchanged.
- **AC-02:** a request with two authorized versions can retrieve and cite both.
- **AC-03:** one denied/missing version causes the whole selected file scope to
  return no evidence; content from remaining files is not silently answered.
- **AC-04:** duplicate, empty, oversized and mixed-scope contracts are rejected.
- **AC-05:** composer selects/removes up to five existing authorized files and
  submits exact immutable `version_ids`.
- **AC-06:** a successful composer upload becomes a ready attachment only after
  terminal server acceptance; failed uploads do not enter the Ask payload.
- **AC-07:** upload and Ask access loss clear private attachment state.
- **AC-08:** keyboard, screen-reader and narrow-screen interactions remain usable.
- **AC-09:** backend/web unit, integration, lint, type, build and focused browser
  checks pass without external LLM or embedding calls.

## 6. Work packages

1. **Contract and retrieval:** bounded multi-version filter, all-or-nothing ACL
   gate and globally budgeted file-union retrieval.
2. **Composer workflow:** multi-select catalog, shared upload handoff, progress,
   duplicate/limit handling and immutable Ask payload.
3. **Premium UI:** compact monochrome context dock consistent with the current
   ChatGPT-like composer; no ornamental cards or layout shift.
4. **Verification:** regression, security boundary, accessibility, responsive
   and build evidence; Completion and Verify Reports.

## 7. Closure

All acceptance criteria passed on the local worktree and rebuilt primary
runtime on 15/08/2026. No LLM or embedding endpoint was called. The result is
included in the joint TIP-036/TIP-037 milestone publication and does not alter
the production-release gates.

- [Completion Report](./TIP-037_COMPLETION_REPORT.md)
- [Verify Report](./TIP-037_VERIFY_REPORT.md)
