# TIP-008 Completion Report

STATUS: DONE

## REQUIREMENT COVERAGE

- Implemented: REQ-004, REQ-006, REQ-013, REQ-014, REQ-017, REQ-018,
  REQ-019, REQ-021, REQ-026, REQ-027 and REQ-029.
- Advanced: the typed file locator/evidence contract that TIP-011 can consume.
- Missing within TIP-008 scope: 0.
- Collaborative Office editing, document/template generation and the unified Ask
  experience remain in later TIPs by design.

## FILES CHANGED

- Backend contract and endpoints:
  `apps/backend/src/rtr_copilot/ingestion/api.py`,
  `apps/backend/src/rtr_copilot/ingestion/models.py`,
  `apps/backend/src/rtr_copilot/repositories/resources.py` and
  `apps/backend/src/rtr_copilot/storage/s3.py`.
- Backend tests:
  `apps/backend/tests/test_ingestion_unit.py` and
  `apps/backend/tests/test_ingestion_integration.py`.
- Same-origin web boundary:
  `apps/web/src/app/api/files/[[...path]]/route.ts`, its route tests,
  `apps/web/src/proxy.ts`, `proxy.test.ts` and `next.config.ts`.
- Raw HTTP path defense:
  `infra/docker/web-guard.mjs` and `infra/docker/web.Dockerfile`.
- Viewer contracts and registry:
  `apps/web/src/files/contracts.ts`, `apps/web/src/files/viewers.tsx` and
  `apps/web/src/files/contracts.test.ts`.
- Workspace:
  `apps/web/src/app/page.tsx`, `page.test.tsx`, `styles.css` and `layout.tsx`.
- Browser coverage:
  `apps/web/tests/browser/files.spec.ts` replaces the foundation-only browser
  scenario.
- Operator documentation: `v2/README.md`.
- Gate accounting: `v2/scripts/verify-data-integration.sh`.
- Completion evidence: this report.

## MIGRATION

- No migration was required.
- Schema head remains `0007_hybrid_rag_grounded_answers`.
- Existing seven-revision upgrade/downgrade and fixture gates remain green.

## AUTHORIZATION AND FILE-DELIVERY EVIDENCE

- Catalog and upload-target queries resolve active user, group, role, department
  and project principals through one effective-principal path. Explicit deny
  retains precedence.
- Object resources resolve their document-version/document/source lineage before
  policy evaluation. Manifest, rendition, original, catalog and upload-target
  paths use fresh server-side authorization rather than UI capability state.
- Catalog ordering is stable, metadata is policy-filtered before serialization,
  the cursor is opaque and HMAC-authenticated, and no total count is returned.
- Original download requires both version-lineage and object `download`
  authorization. Catalog capability uses that identical two-part decision;
  version allow plus object deny is false in catalog, manifest and original.
- Full, bounded, open-ended and suffix byte ranges use exact `200/206/416`
  semantics. Authorization occurs before object metadata/range behavior.
- Response filenames are normalized. File bytes use `nosniff`,
  `private, no-store`, immutable checksum ETag and safe disposition headers.
- The container's raw HTTP guard rejects literal, encoded and repeatedly encoded
  dot traversal before Node/Next URL normalization. The Next proxy and route add
  defense in depth, accept only the `/api/files` boundary, forward fixed request
  and response header allowlists (including `nosniff`) and stream both bodies.
  Upstream hosts, storage keys, bearer credentials and hop-by-hop headers do not
  cross the boundary.

## WORKSPACE AND VIEWER EVIDENCE

- Anonymous sessions render only login/readiness and issue zero file requests.
- Authenticated sessions get a three-surface Files workspace: authorized catalog,
  safe viewer and Evidence Rail. Search, type filters, cursor pagination, errors,
  retry, browser history and immutable version URLs are implemented.
- Upload uses an authorized target and raw request stream with bounded
  polling/backoff, terminal cancellation and server-controlled retryability.
  The optional client checksum was removed because browser WebCrypto required a
  full-file `arrayBuffer`; the backend computes and persists the authoritative
  checksum while streaming.
- Upload-target discovery keyset-scans all active sources in batches of 200
  instead of silently stopping after 500 candidates. A target after the first
  scan batch is covered by integration regression.
- The closed viewer registry supports image, PDF, DOCX, XLSX, PPTX, video and
  audio. It consumes only manifest-authorized same-origin rendition URLs.
- Manifest runtime validation covers state, capability booleans, rendition
  UUID/URL identity, checksum, quality state and bounded string warnings. JSON
  rendition loading is bounded to 20 MB/64 manifest renditions; recursive result
  search is bounded to 100 matches. Unsafe URLs, malformed manifests and hostile
  locators fail safely.
- Image uses metadata-stripped safe preview/OCR; PDF and Office use safe PDF plus
  extracted semantic structure; XLSX exposes tabs, row/cell headers, merged
  ranges, formula/value distinction and exact cells; media uses native controls,
  range-capable safe streams and activated transcript timecodes.
- Semantic DOCX/PPTX preview explicitly warns that layout fidelity may differ.
  No original OOXML package, arbitrary remote URL or executable markup is
  rendered. `dangerouslySetInnerHTML` is not used.
- `rtr.locator.v1` state is strictly parsed, bounded, restored through browser
  navigation and copyable as a deep link. The locator spine and Evidence Rail
  update from page, region, paragraph, sheet/cell, slide/shape or timecode.
- XLSX sheet selection derives from the current locator, so search and
  back/forward navigation can activate a different sheet without stale local
  tab state.
- JSON rendition `401/403/404` notifies one centralized access-loss handler.
  Catalog/session loss clears files, targets, manifest, selection and evidence;
  selected-resource `404` clears only that selection. Focus/visibility
  revalidates the manifest for native image/PDF/media surfaces.
- Original download is shown only for
  `capabilities.download_original=true`; stale UI state cannot bypass backend
  reauthorization.

## TEST RESULTS

- Full `make verify`: **PASS**, exit 0.
- Ruff: pass.
- Strict mypy: **62 source files**, pass.
- Backend: **159 passed, 35 skipped** environment integrations.
- Isolated PostgreSQL/data integration: **34 passed**.
- Migration revisions/fixtures: **7/7**; failing-DDL rollback: **1/1**.
- Existing format/output gates: **14 input formats, 31 required outputs**.
- Existing policy matrix: **48 scenarios**; runtime mutation denials:
  **18/18**.
- Frontend unit: **28/28** across four files.
- ESLint, TypeScript and Next production build: pass after the final UI change.
- Production Playwright: **15/15 passed** across seven viewer families,
  upload failure/retry/success, anonymous gating, cross-sheet locator activation,
  JSON/native rendition revocation, session revocation and
  mobile/tablet/desktop keyboard/responsive flows.
- Image/container build: pass.
- Trivy: **0** OS/Python vulnerabilities.

| AC | Result | Evidence |
|---|---|---|
| AC-01 Catalog policy | PASS | owner/cross-owner integration, effective-principal filter, signed cursor |
| AC-02 Upload targets | PASS | policy-filtered keyset scan; authorized target beyond first batch |
| AC-03 Separate download | PASS | version allow + object deny false across catalog/manifest/original |
| AC-04 Byte ranges | PASS | full/bounded/open/suffix/invalid/unsatisfiable tests |
| AC-05 Narrow proxy | PASS | raw/encoded traversal 400, fixed headers, `nosniff`, streaming |
| AC-06 Authentication gate | PASS | unit plus Playwright zero-file-request regression |
| AC-07 Catalog interaction | PASS | search/filter/cursor/select/history plus session-loss clearing |
| AC-08 Upload lifecycle | PASS | integration plus Playwright failed/retryable/accepted flow |
| AC-09 Image/PDF | PASS | deterministic safe-rendition browser flows and locator search |
| AC-10 DOCX/PPTX | PASS | safe PDF/semantic renditions and explicit fidelity warning |
| AC-11 XLSX | PASS | tabs/grid/formula/value/merged-range and cross-sheet locator coverage |
| AC-12 Media | PASS | audio/video viewers, range endpoint and transcript activation |
| AC-13 Safe failure | PASS | full hostile-manifest validation and centralized revocation clearing |
| AC-14 Evidence Rail | PASS | version/hash/locator/quality and capability-gated download |
| AC-15 Deep links | PASS | hostile/bounded locator unit cases and history restoration |
| AC-16 Accessibility/responsive | PASS | 3 px focus, keyboard/Escape, 360/768/1440 no-overflow flows |
| AC-17 Leak regression | PASS | anonymous/cross-owner/effective-deny/rendition/original probes; leak 0 |
| AC-18 Full health | PASS | full verify, production browser run and healthy runtime smoke |

## RUNTIME SMOKE

- Fresh API, worker and web containers reported ready; ClamAV, MinIO and worker
  health checks passed.
- Corporate development OIDC flow produced an authenticated persisted staff
  session: `/api/auth/me` **200**.
- Same-origin authorized catalog and upload targets returned **200**; anonymous
  catalog returned **401**.
- An authorized viewer manifest returned **200** with two safe renditions.
- A live same-origin rendition request with `Range: bytes=0-9` returned **206**,
  exact `Content-Range: bytes 0-9/78`, `Cache-Control: private, no-store` and
  `X-Content-Type-Options: nosniff`.
- The same view-only item reported `download_original=false`; original access
  returned opaque **404**.
- Live `curl --path-as-is` probes returned **400** for
  `/api/files/%2e%2e/auth/me`, double-encoded traversal and literal dot
  traversal, while the legitimate `/api/auth/me` remained **200**.
- Screenshots:
  - `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/web/test-results/tip008-desktop.png`
  - `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/web/test-results/tip008-mobile.png`

## ISSUES

- No P0, P1 or P2 issue remains within TIP-008 scope.
- P3: automated contrast tooling was not added as a new dependency. Focus,
  keyboard behavior, responsive overflow and the approved token palette were
  verified by browser tests and visual inspection.

## DEVIATIONS

- DOCX and PPTX preview is semantic/PDF-based rather than layout-faithful native
  Office rendering. The limitation is surfaced in warnings as required by the
  approved TIP.
- Browser-native PDF/media controls are used over authorized safe renditions;
  no external viewer SaaS or new remote dependency was introduced.
- A minimal dependency-free raw HTTP guard fronts the generated standalone Next
  server because Next normalizes encoded dot segments before application routes.
  It streams requests/responses to an internal loopback port and fails closed on
  malformed or repeatedly encoded paths.
- File-scoped final Ask composition remains deferred to TIP-011. TIP-008 exposes
  deterministic locators and copyable evidence links for that integration.

## SUGGESTIONS

- Add an axe-based accessibility job when the project approves that locked
  development dependency.
- Calibrate catalog page size, payload ceiling and upload poll intervals against
  representative authorized production workloads without weakening current
  hard bounds.
- TIP-011 should consume the existing `rtr.locator.v1` and Evidence Rail
  contracts rather than duplicating viewer authorization in the browser.

## DATA-SAFETY CONFIRMATION

- Denied bytes, filenames, counts and content-derived metadata were not exposed.
- No object-store key, internal upstream hostname or authorization token was
  returned to the browser.
- Tests and screenshots use deterministic synthetic fixtures only.
- No real company source data was copied, indexed or modified.
- `/Users/os/RtR/kernel`, KnowledgeBase registries, GOI packs and research
  corpora were not read into the feature, modified or indexed.
