# TIP-008 · File Workspace & Multi-format Viewers

## HEADER

- **TIP-ID:** TIP-008
- **Project:** RtR Copilot V2
- **Module:** Files workspace, viewer API and web experience
- **Depends on:** TIP-003, TIP-004, TIP-005 VERIFIED
- **Priority:** P0
- **Status:** VERIFIED · READY
- **Working directory:** `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2`
- **Requirements directly implemented/advanced:** REQ-004, REQ-006, REQ-013,
  REQ-014, REQ-017, REQ-018, REQ-019, REQ-021, REQ-026, REQ-027, REQ-029

## CONTEXT

TIP-005 already provides immutable originals, quarantine/AV/MIME validation,
14 supported input formats, 31 required rendition outputs, viewer manifests,
request-time authorization and safe rendition streaming. It intentionally stopped
before a user-facing Files workspace.

The current web is only a signed-in foundation screen. The viewer contract is
usable but incomplete for a real workspace:

- there is no authorized file catalog or upload-target discovery endpoint;
- there is no original-download endpoint;
- media streaming does not yet implement HTTP byte ranges;
- the browser has no same-origin proxy for file APIs;
- no image/PDF/Office/spreadsheet/media viewer or deep locator UX exists.

This TIP completes the end-to-end **open and understand a file** flow. It does not
add collaborative Office editing, template/document generation, research
graduation or the final unified Ask experience.

## DECISIONS LOG

| ID | Decision | Rationale |
|---|---|---|
| D-008-01 | Reuse the TIP-005 rendition contract; never parse untrusted originals in the browser | Preserve quarantine and safe-preview boundary |
| D-008-02 | Files UI obtains all bytes through same-origin authenticated routes | Avoid CORS, presigned-URL and cookie leakage |
| D-008-03 | `view` and `download` remain separate decisions | Preview must never imply original-download authority |
| D-008-04 | Deep locators use `rtr.locator.v1` in the URL and viewer state | Citations survive navigation and can later feed Evidence Rail |
| D-008-05 | Native browser PDF/media elements are permitted over safe renditions | No new viewer dependency is required for this TIP |
| D-008-06 | Office editing is deferred; DOCX/PPTX use PDF/text renditions and XLSX uses a bounded semantic grid | Matches approved OQ-004 |
| D-008-07 | Blueprint approval is reused; no new Homeowner checkpoint | This TIP implements the already-approved M3 architecture |

## DESIGN DIRECTION

**Subject:** an evidence-first technical file console for RtR engineers,
operations and business staff.

**Single job:** let a permitted employee select, inspect, search, locate and
download a company file without leaving RtR Copilot.

### Token plan

| Role | Token |
|---|---|
| Deep graphite | `#0D0F11` |
| Instrument panel | `#15191C` |
| Structural line | `#2B3034` |
| Primary ink | `#E8E6E3` |
| Muted steel | `#92999F` |
| RtR signal orange | `#E56B46` |
| Locator cyan | `#76A8B3` |

- Display/navigation: condensed industrial stack (`Arial Narrow`,
  `Helvetica Neue Condensed`, sans-serif).
- Body: `Helvetica Neue`, Arial, sans-serif.
- Locators/checksums/data: `ui-monospace`, SFMono-Regular, monospace.
- Do not add a remote font dependency.

### Layout

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ RT ROBOTICS / FILES       Search files                identity / upload │
├───────────────┬──────────────────────────────────────┬──────────────────┤
│ Catalog       │ Safe work surface                    │ Evidence rail    │
│ filters       │                                      │ version / hash   │
│ file list     │ image / PDF / sheet / slide / media │ locator / quality│
│ upload state  │                                      │ download action  │
└───────────────┴──────────────────────────────────────┴──────────────────┘
```

At tablet/mobile widths the catalog becomes a drawer and Evidence Rail becomes a
bottom sheet. The viewer remains the dominant surface.

### Signature element

Use a **locator spine**: a restrained cyan technical ruler at the viewer edge
whose active tick mirrors page, sheet/cell, slide or timecode. It is structural,
not decorative, and gives the Files workspace a recognizable evidence-first
identity.

### Self-critique constraint

Avoid generic dashboard card grids, decorative gradients, glass effects, oversized
marketing headings and arbitrary status colors. Spend visual emphasis on the
viewer/locator relationship; keep the catalog and metadata quiet and dense.

## TASK

### 1. Authorized catalog and upload targets

Extend `/api/v1/files` with typed, cursor-paginated endpoints:

- `GET /api/v1/files`
  - returns only active documents/versions the subject may `view`;
  - fields: immutable IDs, logical/display filename, detected MIME, viewer kind,
    viewer state, byte size, classification, owner display metadata safe for the
    caller, version timestamp, quality/warnings, `can_download`;
  - supports bounded `limit`, opaque cursor, MIME/viewer-kind filter and normalized
    filename query;
  - policy-filter before returning content-derived fields;
  - resolve the complete effective-principal set (user, group, role, department
    and project) with explicit deny precedence; direct-user-only ACL evaluation is
    forbidden;
  - no total count or timing distinction may reveal denied documents.
- `GET /api/v1/files/upload-targets`
  - returns only active resources the subject may `upload` into;
  - includes immutable target ID and safe display label;
  - empty list is valid and must give the UI an actionable state.

Catalog ordering must be stable and cursor-safe. Invalid cursor/filter returns a
typed `400`; anonymous returns `401`; denied/non-visible resource lookups remain
`404`.

### 2. Original download and byte ranges

Add:

- `GET /api/v1/files/versions/{version_id}/original`
  - requires fresh `download` authorization on both effective version/document
    lineage and the original object;
  - returns immutable original bytes with safe `Content-Disposition: attachment`,
    `nosniff`, private/no-store and checksum ETag;
  - filename is normalized and cannot inject response headers;
  - every allow/deny is audited without logging sensitive filename or object key.

Add single-range support to rendition content and original download:

- valid `Range: bytes=start-end`, open-ended and suffix ranges return `206`,
  correct `Content-Range`, `Content-Length` and `Accept-Ranges: bytes`;
- invalid/multiple/unsatisfiable ranges return `416` without object bytes;
- authorization completes before object metadata or range behavior is observable;
- full response remains `200`;
- HEAD is not required unless naturally supported.

### 3. Same-origin web proxy

Create a narrowly scoped Next.js proxy for `/api/files/[...path]`:

- forwards only file endpoints to `/api/v1/files/...`;
- forwards session cookie, request ID and an explicit allowlist of request headers
  required for upload, content type/length/hash and byte ranges;
- streams request/response bodies without buffering large files;
- forwards only safe response headers (`content-type`, `content-length`,
  `content-range`, `accept-ranges`, `content-disposition`, `etag`,
  `cache-control`, `x-request-id`);
- never forwards upstream/internal hostnames, object keys, authorization tokens or
  arbitrary hop-by-hop headers;
- uses bounded upstream connection/error handling and a typed safe failure.

### 4. Files workspace

Replace the signed-in foundation-only experience with the Files workspace while
retaining the existing corporate login and readiness behavior:

- anonymous users see the identity gate and cannot load catalog data;
- authenticated users see catalog, viewer surface and Evidence Rail;
- catalog has search, type filters, stable pagination/load-more, loading,
  empty, offline/error and retry states;
- selecting a file updates a shareable URL using immutable `version_id`;
- reload/back/forward restore the selected version and locator;
- no inaccessible filename or count is cached in local/session storage;
- selected state is cleared and content removed after `401/403/404`.

### 5. Upload workflow

Implement keyboard-accessible file picker and drag/drop:

- target is selected from authorized upload targets;
- accepted-format copy matches the backend's 14 input MIME/extension matrix;
- stream the file to the proxy with required immutable target/name/hash headers;
- show upload, validation, scanning, extraction/rendition progress;
- poll with bounded backoff, stop on terminal/unmount and avoid duplicate polling;
- expose typed, actionable errors and retry only when backend says `retryable`;
- on success refresh/select the resulting version without a full page reload;
- client hints never replace server MIME/AV/quota validation.

### 6. Viewer registry

Build a typed viewer registry keyed by `viewer_kind`. Every viewer consumes only
authorized safe renditions from the manifest:

- **Image:** safe image rendition with fit/actual-size controls; OCR text/regions
  when present; no source EXIF or original rendering.
- **PDF:** `preview_pdf` in-app with page locator and extracted page text/search.
- **DOCX:** `preview_pdf` plus structured paragraph/table outline; paragraph deep
  link. If the available renderer is semantic rather than layout-faithful, label
  that limitation in quality/warnings instead of presenting it as exact Office
  fidelity.
- **XLSX:** bounded workbook/sheet JSON grid with sheet tabs, row/column headers,
  merged-range indication, formula/value distinction and cell deep link.
- **PPTX:** `preview_pdf`/slide preview plus slide outline/notes; slide deep link.
  Any reduced visual fidelity must be explicit in quality/warnings.
- **Video:** `browser_video`, poster, native controls, byte-range seek and
  transcript timecodes.
- **Audio:** `browser_audio`, waveform, native controls, byte-range seek and
  transcript timecodes.

Viewer payload parsing must be runtime-validated, bounded and fail into a safe
partial-preview state. Never use `dangerouslySetInnerHTML`, execute Office content,
embed an original OOXML file or render arbitrary remote URLs.

### 7. Search and deep locators

- Search within authorized extracted text only.
- Match display is bounded and HTML-escaped.
- Activating a result navigates to the exact locator:
  - PDF/image OCR: page/region;
  - DOCX: paragraph/table;
  - XLSX: sheet/cell;
  - PPTX: slide/shape;
  - audio/video: `t` in milliseconds.
- URL parameters are strictly parsed and bounded; malformed locators are ignored
  with a non-blocking notice.
- Transcript results seek media only after user activation.

### 8. Evidence Rail and download ownership

The right rail shows:

- safe display name, viewer kind/MIME, immutable version ID;
- truncated checksum with copy affordance;
- current `rtr.locator.v1` locator;
- rendition quality/warnings and OCR/transcript availability;
- explicit preview/download capability distinction.

Show “Tải bản gốc” only when `download_original=true`. Backend remains authoritative:
a stale client capability must still fail closed. Download errors do not replace
the current safe preview.

### 9. Accessibility and responsive behavior

- Semantic landmarks, one H1, correct labels and status announcements.
- Complete primary flow by keyboard: login → catalog → select → search → locator →
  download/upload.
- Visible focus at least 3 CSS pixels; no focus trap; Escape closes drawers/sheets.
- Minimum WCAG 2.2 AA contrast; signal colors are never the only state cue.
- 360×800, 768×1024, 1440×900 and 1920×1080 have no accidental horizontal page
  overflow; data grid may scroll inside its labeled region.
- Respect reduced motion; no essential information depends on animation.
- Vietnamese UI copy for TIP-008. Full i18n framework remains TIP-011.

### 10. Tests, runtime proof and documentation

Add:

- backend unit/integration tests for catalog policy filtering, cursor safety,
  upload-target discovery, original download, range semantics and audit;
- frontend unit tests for registry selection, manifest/payload validation,
  locator parsing, capability gating and access-revocation clearing;
- Playwright flows at mobile/tablet/desktop using deterministic safe fixtures for
  every viewer family, upload progress/retry, keyboard use and responsive layout;
- explicit leak probes for anonymous, cross-owner, denied classification, stale
  capability, denied rendition and range side-channel;
- screenshot evidence at desktop and mobile for Contractor review;
- README API/UI/operator notes.

Keep `make verify` as the single full gate. The gate must remain concurrency-safe
and preserve all TIP-001…007 tests.

## ACCEPTANCE CRITERIA

### AC-01 · Catalog is policy-filtered

**Given** allowed and denied documents interleaved in stable ordering  
**When** a user lists, filters or paginates Files  
**Then** only authorized metadata appears and no count/cursor/timing contract leaks
denied existence.

### AC-02 · Upload targets are authorized

**Given** mixed resources with upload allow/deny assignments  
**When** upload targets are requested  
**Then** only effective `upload` allows appear and an empty authorized set is safe.

### AC-03 · Original download is separate and fail-closed

**Given** a user can view but cannot download a version  
**When** manifest and original endpoints are called  
**Then** preview succeeds, download capability is false and original access is
denied without existence leakage.

### AC-04 · Byte ranges are correct

**Given** authorized media and original objects  
**When** full, bounded, open-ended, suffix, invalid and unsatisfiable ranges are
requested  
**Then** `200/206/416`, lengths and content ranges are byte-exact.

### AC-05 · Same-origin proxy is narrow

**Given** authenticated and hostile proxy requests  
**When** headers, paths and response headers are exercised  
**Then** only the allowlisted file contract crosses the boundary and streaming does
not buffer whole media/files.

### AC-06 · Authentication gate

**Given** no valid corporate session  
**When** Files loads  
**Then** only the login/readiness state appears and no catalog/manifest/content
request is issued.

### AC-07 · Catalog interaction

**Given** an authenticated subject with multiple allowed files  
**When** they search, filter, paginate, select and navigate browser history  
**Then** catalog and selected immutable version remain consistent without forbidden
client persistence.

### AC-08 · Upload lifecycle

**Given** valid, rejected and retryable uploads  
**When** a user uploads through an allowed target  
**Then** progress/terminal states are accurate, retry obeys backend capability and
successful output opens without reload.

### AC-09 · Image/PDF viewers

**Given** authorized image and PDF manifests  
**When** opened  
**Then** safe renditions render in-app and OCR/page search navigates to exact
locators.

### AC-10 · DOCX/PPTX viewers

**Given** authorized DOCX and PPTX manifests  
**When** opened  
**Then** safe PDF/text/slide renditions render without executing or embedding the
original Office package.

### AC-11 · XLSX viewer

**Given** a bounded authorized workbook rendition  
**When** sheet and search/cell results are activated  
**Then** tabs, headers, values/formulas, merged-range state and exact cell locator
are represented safely.

### AC-12 · Media viewers

**Given** authorized audio/video with transcript renditions  
**When** played, sought and a transcript timecode is activated  
**Then** safe media streams with byte ranges and current locator follows playback.

### AC-13 · Payload failure is safe

**Given** malformed, oversized, partial or revoked viewer payloads  
**When** the workspace loads them  
**Then** it shows a bounded partial/error state, clears revoked content and never
executes markup or remote URLs.

### AC-14 · Evidence Rail capability truth

**Given** view-only and view-plus-download files  
**When** selected  
**Then** rail metadata/locator/quality is accurate and original download appears
only for the latter while server reauthorization remains decisive.

### AC-15 · Deep links are deterministic

**Given** valid and hostile locator query parameters  
**When** a version URL is opened or reloaded  
**Then** valid locators restore exact context and malformed locators are bounded and
ignored safely.

### AC-16 · Accessibility and responsive layout

**Given** keyboard-only use, reduced motion and target viewports  
**When** the primary flow is completed  
**Then** focus/order/announcements/contrast meet the TIP and no page-level overflow
or trapped focus occurs.

### AC-17 · Authorization leak regression

**Given** anonymous, cross-owner, denied-classification, stale-policy and directly
denied rendition scenarios  
**When** catalog, manifest, content, range, upload and original endpoints are
probed  
**Then** leak count is zero and allow/deny audit events use immutable subject IDs.

### AC-18 · Full health gate

**Given** all TIP-001…008 changes  
**When** `make verify` and runtime smoke execute  
**Then** lint, strict types, unit/integration/browser tests, migrations, security
scan and healthy local services pass with schema unchanged unless an explicitly
documented migration is required.

## CONSTRAINTS

- Preserve existing OIDC/session, policy engine, immutable ownership, audit chain,
  object storage and ingestion contracts.
- Do not authorize from filename, email, UI visibility or cached manifest state.
- Do not expose object-store URLs/keys or use public buckets/presigned URLs.
- Do not index private attachments into SOT.
- Do not implement collaborative Office editing, templates, Documents OS,
  research/admin flows or final unified Ask/Evidence Rail from TIP-009…011.
- Do not modify or index `/Users/os/RtR/kernel`, KnowledgeBase registries,
  GOI packs or research corpora.
- Do not add a remote font, analytics service or external file-viewer SaaS.
- New dependencies require a concrete need, locked versions and security scan.

## REPORT FORMAT

Create `vibecode_v2/TIP-008_COMPLETION_REPORT.md` with:

- `STATUS: DONE | PARTIAL | BLOCKED`;
- REQ coverage implemented/advanced/missing;
- files created/modified and any migration;
- AC-01…AC-18 evidence;
- exact test/build/security/browser counts;
- runtime smoke and screenshot paths;
- issues, deviations and suggestions;
- explicit confirmation that denied bytes/metadata, object keys and real company
  source data were not exposed or modified.
