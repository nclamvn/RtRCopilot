/**
 * TIP-011 Builder D — shared route-mock helpers for the axe (a11y.spec.ts)
 * and keyboard (keyboard.spec.ts) suites. These mirror the house route-mock
 * conventions of the per-page specs (ask/files/documents/knowledge-ops
 * .spec.ts keep their own local copies untouched); synthetic fixtures only
 * (D-011-08).
 */

import type {Page} from "@playwright/test";

export const ids = {
  conversationId: "11111111-1111-4111-8111-111111111111",
  runId: "22222222-2222-4222-8222-222222222222",
  gapId: "33333333-3333-4333-8333-333333333333",
  requesterId: "44444444-4444-4444-8444-444444444444",
  versionId: "55555555-5555-4555-8555-555555555555",
  documentId: "66666666-6666-4666-8666-666666666666",
  chunkId: "77777777-7777-4777-8777-777777777777",
  renditionId: "99999999-9999-4999-8999-999999999999",
  dataRenditionId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  peerId: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
  packageId: "12121212-1212-4121-8121-121212121212",
  recordId: "13131313-1313-4131-8131-131313131313",
  proposalId: "14141414-1414-4141-8141-141414141414",
  publishPackageId: "15151515-1515-4151-8151-151515151515",
  templateId: "16161616-1616-4161-8161-161616161616",
  templateVersionId: "17171717-1717-4171-8171-171717171717",
  renderJobId: "18181818-1818-4181-8181-181818181818",
  generatedId: "19191919-1919-4191-8191-191919191919",
  fileVersionId: "20202020-2020-4202-8202-202020202020",
  docRenditionId: "21212121-2121-4212-8212-212121212121",
};

export const sha = "a".repeat(64);

export const pilotReadiness = {
  computed_at: "2026-08-04T08:00:00Z",
  sot: {active_records: 219, strict_records: 8, caveated_records: 211,
    current_records: 219, stale_records: 0, named_owner_records: 0,
    placeholder_owner_records: 219, caveated_named_owner_records: 0,
    caveated_placeholder_owner_records: 211, high_risk_records: 20,
    high_risk_caveated_records: 12, zone_masquerade_findings: 0},
  files: {documents: 30, versions: 30, representative_versions: 30,
    ready_versions: 30, indexed_versions: 30,
    viewer_families: {pdf: 8, docx: 8, xlsx: 7, image: 7},
    original_checksum_mismatches: 0, rendition_lineage_mismatches: 0},
  templates: {templates: 4, approved_templates: 4, locked_bindings: 10,
    official_or_legal_approved: 0},
  research: {active_sources: 1, imported_packages: 1, records: 70,
    tiers: {P: 70}, corroboration: {corroborated: 16, disputed: 24, uncorroborated: 30}},
  question_count: 32,
  gates: [
    {gate_key: "sot_gold_baseline", target: 8, actual: 8, state: "met", detail: "Strict records retained"},
    {gate_key: "caveated_named_owners", target: 211, actual: 0, state: "blocked", detail: "Human owners required"},
  ],
  production_boundary: "local_dev_only",
};

export async function mockAuth(page: Page) {
  await page.route("**/api/auth/me", route => route.fulfill({json: {
    user_id: ids.requesterId, email: "staff@rtrobotics.com",
    display_name: "RtR Staff", roles: ["staff", "curator"],
  }}));
  await page.route("**/api/status", route => route.fulfill({json: {
    ok: true, status: "ready",
  }}));
}

/** Admin workspace control-plane fixture: operational snapshot plus empty
 * bounded registries. No truth-family route is exposed by this mock. */
export async function mockAdmin(page: Page) {
  await mockAuth(page);
  await page.route("**/api/governance/admin/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/governance/admin/jobs/health") return route.fulfill({json: {
      computed_at: "2026-08-04T08:00:00Z", families: [
        {family: "ingestion", job_counts: {completed: 8}, outbox_counts: {published: 8}, recent_failures: []},
        {family: "render", job_counts: {completed: 4}, outbox_counts: {published: 4}, recent_failures: []},
        {family: "reindex", job_counts: {completed: 3}, outbox_counts: {published: 3}, recent_failures: []},
      ],
    }});
    if (path === "/api/governance/admin/pilot-readiness") {
      return route.fulfill({json: pilotReadiness});
    }
    if (["/api/governance/admin/subjects", "/api/governance/admin/research-sources", "/api/governance/admin/settings"].includes(path)) {
      return route.fulfill({json: []});
    }
    return route.fulfill({status: 404, json: {error: {code: "not_found", message: ""}, request_id: "req-admin"}});
  });
}

const citation = {
  zone_label: "sot",
  marker: "C1", chunk_id: ids.chunkId, record_key: "company.warranty",
  record_version_id: ids.versionId, evidence_key: "company.warranty.e1",
  record_checksum: sha, evidence_checksum: "b".repeat(64),
  source_key: "rtr.specs", source_revision: 3,
  provenance_level: "approved_internal", verification_state: "approved",
  freshness_state: "current", source_label: "Company specification",
  locator: {page: 4}, redacted: false,
};

export const groundedAnswer = {
  state: "grounded", answer: "Robot RtR được bảo hành 24 tháng. [C1]",
  citations: [citation], conversation_id: ids.conversationId,
  answer_run_id: ids.runId, request_id: "req-ask-1",
};

export const honestNullAnswer = {
  state: "honest_null",
  answer: "Không tìm thấy bằng chứng được phép và đủ tin cậy để trả lời.",
  citations: [], conversation_id: ids.conversationId,
  answer_run_id: ids.runId, gap_id: ids.gapId, request_id: "req-ask-2",
};

function pdfManifest(versionId: string, renditionId: string, dataRenditionId: string) {
  return {
    schema_version: 1, version_id: versionId, source_sha256: sha,
    detected_mime: "application/pdf", viewer_kind: "pdf", state: "ready",
    capabilities: {preview: true, text: true, search_within_file: true,
      deep_link: true, download_original: false},
    renditions: [
      {rendition_id: renditionId, kind: "preview_pdf",
        mime_type: "application/pdf", byte_size: 120, sha256: sha,
        quality_state: "complete",
        content_url: `/api/v1/files/renditions/${renditionId}/content`},
      {rendition_id: dataRenditionId, kind: "page_text_json",
        mime_type: "application/json", byte_size: 120, sha256: sha,
        quality_state: "complete",
        content_url: `/api/v1/files/renditions/${dataRenditionId}/content`},
    ],
    locator_schema: "rtr.locator.v1", quality: {}, warnings: [],
  };
}

/** Files catalog + PDF viewer mocks (used by /ask file scope and /files). */
export async function mockFiles(page: Page) {
  await page.route("**/api/files**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/files") {
      return route.fulfill({json: {items: [{
        document_id: ids.documentId, version_id: ids.versionId,
        logical_name: "rtr.specs", display_filename: "company-spec.pdf",
        detected_mime: "application/pdf", viewer_kind: "pdf",
        viewer_state: "ready", byte_size: 120, classification: "internal",
        owner_display_name: "RtR Staff",
        version_created_at: "2026-07-31T00:00:00Z", quality: {}, warnings: [],
        can_download: false,
      }], next_cursor: null}});
    }
    if (path.endsWith("/upload-targets")) return route.fulfill({json: {items: []}});
    if (path.endsWith("/viewer-manifest")) {
      return route.fulfill({
        json: pdfManifest(ids.versionId, ids.renditionId, ids.dataRenditionId),
      });
    }
    if (path.includes("/renditions/")) {
      return route.fulfill({json: {pages: [{page: 4, text: "Warranty 24 months"}]}});
    }
    return route.fulfill({status: 404, json: {error: {code: "not_found"}}});
  });
}

/** Ask workspace mocks (scope capability, conversations, ask answers). */
export async function mockAsk(page: Page, answer: Record<string, unknown> = groundedAnswer) {
  await mockAuth(page);
  await mockFiles(page);
  await page.route("**/api/governance/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/governance/research/scope") {
      return route.fulfill({json: {allowed: true}});
    }
    if (path === "/api/governance/research/search") {
      return route.fulfill({json: {
        zone_label: "research", grounding: "research_supported",
        results: [], request_id: "req-research-0",
      }});
    }
    if (path === `/api/governance/gaps/${ids.gapId}`) {
      return route.fulfill({json: {
        gap: {
          zone_label: "sot", gap_id: ids.gapId, question_fingerprint: sha,
          sanitized_question: "Điều chưa ai ghi lại?",
          sanitized_summary: "Khoảng trống",
          reason_category: "denied_or_unavailable", classification: "internal",
          requester_id: ids.requesterId, owner_subject_id: null,
          routing_key: "governance.gap", occurrence_count: 1, lifecycle: "open",
          origin: "honest_null", priority: "normal",
          first_seen_at: "2026-08-01T00:00:00Z",
          last_seen_at: "2026-08-01T00:00:00Z",
          triaged_at: null, assigned_at: null, due_at: null, answered_at: null,
          closed_at: null, resolving_version_id: null, decline_reason: null,
        },
        transitions: [],
      }});
    }
    return route.fulfill({status: 404, json: {
      error: {code: "not_found", message: ""}, request_id: "req-x",
    }});
  });
  await page.route("**/api/ask/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/ask/ask") return route.fulfill({json: answer});
    if (path === "/api/ask/conversations") {
      return route.fulfill({json: {
        items: [{
          conversation_id: ids.conversationId,
          started_at: "2026-08-01T00:00:00Z",
          last_activity_at: "2026-08-01T00:00:10Z",
          first_question_digest: sha,
        }],
        next_cursor: null, request_id: "req-list-1",
      }});
    }
    return route.fulfill({status: 404, json: {
      error: {code: "conversation_not_found", message: ""}, request_id: "req-y",
    }});
  });
}

/** Documents workspace mocks with a stateful approve path (draft →
 *  in_review → approved → issued) for the keyboard E2E. */
export async function mockDocuments(page: Page) {
  await mockAuth(page);
  const lifecycle = {state: "draft", approvals: [] as Array<Record<string, unknown>>};
  await page.route("**/api/document-os/**", route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/document-os/templates") {
      return route.fulfill({json: {items: [{
        template_id: ids.templateId, version_id: ids.templateVersionId,
        stable_key: "official.report", display_name: "Báo cáo vận hành",
        category: "Operations", classification: "internal",
        document_class: "official", format: "xlsx", version_ordinal: 3,
        status: "approved", owner_display_name: "Curator",
      }], next_cursor: null}});
    }
    if (path.endsWith(`/templates/${ids.templateId}/versions/${ids.templateVersionId}`)) {
      return route.fulfill({json: {
        template_id: ids.templateId, version_id: ids.templateVersionId,
        status: "approved", source_sha256: sha,
        renderer_kind: "xlsx_declarative", renderer_version: "rtr-doc-os-1",
        schema: {schema_version: 1, bindings: [
          {field_path: "customer_name", field_type: "string", source: "user",
            required: true},
          {field_path: "company_name", field_type: "string",
            source: "locked_fact", required: true, record_key: "company.name"},
        ]},
      }});
    }
    if (path.endsWith("/bind")) {
      return route.fulfill({json: {
        valid: true, missing: [], blocked: [], sot_revision: 9,
        fields: [
          {field_path: "customer_name", source: "user", value: "Nhà máy A"},
          {field_path: "company_name", source: "locked_fact",
            value: "Real-time Robotics", record_key: "company.name",
            record_checksum: "b".repeat(64), evidence_checksum: "c".repeat(64),
            provenance_level: "verified_primary", freshness_state: "current"},
        ],
      }});
    }
    if (path.endsWith("/render") && request.method() === "POST") {
      return route.fulfill({json: {
        render_job_id: ids.renderJobId, state: "pending", progress: 0,
      }});
    }
    if (path.endsWith(`/render-jobs/${ids.renderJobId}`)) {
      return route.fulfill({json: {
        render_job_id: ids.renderJobId, state: "completed", progress: 100,
        generated_file_id: ids.generatedId, version_id: ids.fileVersionId,
        checksum: sha,
      }});
    }
    if (request.method() === "POST" && path.endsWith(`/generated/${ids.generatedId}/submit`)) {
      lifecycle.state = "in_review";
      return route.fulfill({json: {ok: true}});
    }
    if (request.method() === "POST"
        && path.endsWith(`/generated/${ids.generatedId}/decision/approve`)) {
      lifecycle.state = "approved";
      lifecycle.approvals.push({
        approval_id: "23232323-2323-4232-8232-232323232323",
        decision: "approved", reviewer_display_name: "RtR Reviewer",
        reason: "Đã kiểm tra", decided_at: "2026-08-01T01:00:00Z",
      });
      return route.fulfill({json: {ok: true}});
    }
    if (path.endsWith(`/generated/${ids.generatedId}`)) {
      return route.fulfill({json: {
        generated_file_id: ids.generatedId, render_job_id: ids.renderJobId,
        template_version_id: ids.templateVersionId, version_id: ids.fileVersionId,
        output_format: "xlsx", checksum: sha, lifecycle: lifecycle.state,
        render_manifest: {}, created_at: "2026-07-31T00:00:00Z",
        approvals: lifecycle.approvals,
      }});
    }
    if (path.endsWith("/documents/history")) {
      return route.fulfill({json: {
        template_id: ids.templateId, items: [{
          generated_file_id: ids.generatedId,
          template_version_id: ids.templateVersionId,
          version_id: ids.fileVersionId, lifecycle: lifecycle.state,
          checksum: sha, created_at: "2026-07-31T00:00:00Z",
          parameters: {customer_name: "Nhà máy A"},
          locked_snapshots: {company_name: {record_checksum: "b".repeat(64)}},
          comparison: {
            previous_generated_file_id: null,
            changed_parameters: ["customer_name"],
            changed_locked_facts: ["company_name"],
            template_changed: false, checksum_changed: true,
            lifecycle_changed: false,
          },
        }],
      }});
    }
    return route.fulfill({status: 404, json: {error: {code: "not_found"}}});
  });
  await page.route("**/api/files/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/viewer-manifest")) {
      return route.fulfill({json: {
        schema_version: 1, version_id: ids.fileVersionId, source_sha256: sha,
        detected_mime:
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        viewer_kind: "xlsx", state: "ready",
        capabilities: {preview: true, text: true, search_within_file: true,
          deep_link: true, download_original: false},
        renditions: [{rendition_id: ids.docRenditionId,
          kind: "sheet_preview_json", mime_type: "application/json",
          byte_size: 120, sha256: sha, quality_state: "complete",
          content_url: `/api/v1/files/renditions/${ids.docRenditionId}/content`}],
        locator_schema: "rtr.locator.v1", quality: {}, warnings: [],
      }});
    }
    if (path.includes(ids.docRenditionId)) {
      return route.fulfill({json: {sheets: [{
        sheet: "Report",
        rows: [{row: 1, cells: [{cell: "A1", value: "Real-time Robotics"}]}],
        merged_ranges: [],
      }]}});
    }
    return route.fulfill({status: 404, json: {error: {code: "not_found"}}});
  });
}

/** Knowledge Ops mocks incl. the TIP-011 pickers and a stateful gap. */
export async function mockKnowledgeOps(page: Page) {
  await mockAuth(page);
  const gap = {
    lifecycle: "open", owner: null as string | null, due: null as string | null,
    resolving: null as string | null,
    transitions: [] as Array<{from_state: string; to_state: string; reason: string}>,
  };
  const proposal = {state: "proposed", publish: null as string | null};
  const gapJson = () => ({
    zone_label: "sot", gap_id: ids.gapId, question_fingerprint: sha,
    sanitized_question: "Chính sách bảo hành robot RtR là gì?",
    sanitized_summary: "Bảo hành robot", reason_category: "no_evidence",
    classification: "internal", requester_id: ids.peerId,
    owner_subject_id: gap.owner, routing_key: "governance.gap",
    occurrence_count: 3, lifecycle: gap.lifecycle, origin: "honest_null",
    priority: "high", first_seen_at: "2026-07-29T00:00:00Z",
    last_seen_at: "2026-07-31T00:00:00Z", triaged_at: null, assigned_at: null,
    due_at: gap.due, answered_at: null, closed_at: null,
    resolving_version_id: gap.resolving, decline_reason: null,
  });
  const proposalJson = () => ({
    proposal_id: ids.proposalId, research_record_ids: [ids.recordId],
    claim_draft: {claim_text: "ABB là nhà cung cấp robot hàn được RtR tích hợp",
      classification: "internal"},
    target_record_key: "partners.abb", proposer_subject_id: ids.peerId,
    rationale: "Đủ bằng chứng tier P", state: proposal.state,
    decided_by: proposal.state === "proposed" ? null : ids.requesterId,
    decision_reason: null,
    attestation_hash: proposal.state === "approved" ? sha : null,
    publish_package_id: proposal.publish, supersedes_proposal_id: null,
    proposed_at: "2026-07-30T00:00:00Z",
    decided_at: proposal.state === "proposed" ? null : "2026-08-01T00:00:00Z",
  });
  const researchRecord = {
    zone_label: "research", research_record_id: ids.recordId,
    package_id: ids.packageId, package_fingerprint: sha,
    source_key: "refinery.industry", record_key: "vendor.abb.profile",
    version_ordinal: 1, tier: "P",
    content: {name: "ABB", country: "CH/SE"}, searchable_text: "ABB robotics",
    evidence: [{source_url: "https://example.com/abb", locator: {page: 4},
      quoted_text: "ABB manufactures industrial robots for welding lines.",
      checksum: sha}],
    corroboration_state: "corroborated", content_sha256: sha,
    created_at: "2026-07-30T00:00:00Z",
  };
  const dashboard = {
    computed_at: "2026-08-01T00:00:00Z",
    coverage: {zone_label: "sot", total_records: 24, by_source_key: {kernel: 24},
      by_owner: {curator: 24}, by_classification: {internal: 20, restricted: 4}},
    freshness: {zone_label: "sot", total: 5, expiring: 3, expired: 2,
      assigned: 1, unassigned: 4},
    conflict: {zone_label: "sot", total: 1, disputed: 1, superseded_ambiguous: 0,
      assigned: 0, unassigned: 1},
    owner_review: {zone_label: "sot", total: 2, due: 1, overdue: 1,
      assigned: 0, unassigned: 2},
    gap_flow: {zone_label: "sot", open_total: 4, closed_total: 9, overdue: 1,
      by_state: {open: 3, triaged: 1}, aging: {under_24h: 2, days_1_3: 2}},
    research_intake: {zone_label: "research", sources_total: 2,
      sources_active: 2, packages_by_state: {imported: 3, rejected: 1},
      records_by_tier: {P: 5, S: 2}},
    graduation: {zone_label: "research", proposed: 1, approved: 1,
      rejected: 0, submitted: 1},
  };
  const queuePage = (kind: string, entries: unknown[],
    byStatus: Record<string, number>) => ({
    zone_label: "sot", queue_kind: kind, computed_at: "2026-08-01T00:00:00Z",
    entries,
    aggregates: {total: entries.length, by_status: byStatus,
      assigned: 0, unassigned: entries.length},
    next_cursor: null,
  });
  await page.route("**/api/governance/**", route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/governance/governance/dashboard") {
      return route.fulfill({json: dashboard});
    }
    if (path === "/api/governance/governance/pickers/subjects") {
      return route.fulfill({json: {items: [
        {subject_id: ids.peerId, display_name: "RtR Peer",
          email: "peer@rtrobotics.com"},
      ], next_cursor: null}});
    }
    if (path === "/api/governance/governance/pickers/records") {
      return route.fulfill({json: {items: [
        {zone_label: "sot", record_key: "company.warranty",
          record_version_id: ids.versionId, title: "Bảo hành robot",
          classification: "internal"},
      ], next_cursor: null}});
    }
    if (path.startsWith("/api/governance/governance/queues/freshness")) {
      return route.fulfill({json: queuePage("freshness", [{
        zone_label: "sot", queue_kind: "freshness", record_id: ids.peerId,
        record_key: "company.warranty", record_version_id: ids.versionId,
        owner_subject_id: ids.requesterId, classification: "internal",
        status: "expired", sort_at: "2026-07-20T00:00:00Z",
        effective_to: "2026-07-20T00:00:00Z", review_due_at: null,
        sides: [], task: null,
      }], {expired: 1})});
    }
    if (path.startsWith("/api/governance/governance/queues/conflict")) {
      return route.fulfill({json: queuePage("conflict", [], {})});
    }
    if (path.startsWith("/api/governance/governance/queues/owner-review")) {
      return route.fulfill({json: queuePage("owner_review", [], {})});
    }
    if (path === "/api/governance/gaps") {
      return route.fulfill({json: {items: [gapJson()], next_cursor: null}});
    }
    if (path === `/api/governance/gaps/${ids.gapId}`) {
      return route.fulfill({json: {
        gap: gapJson(),
        transitions: gap.transitions.map((item, index) => ({
          sequence: index + 1,
          transition_id: `99999999-9999-4999-8999-${String(index).padStart(12, "0")}`,
          gap_id: ids.gapId, from_state: item.from_state,
          to_state: item.to_state, actor_subject_id: ids.requesterId,
          reason: item.reason, occurred_at: "2026-08-01T01:00:00Z",
        })),
      }});
    }
    if (path.startsWith(`/api/governance/gaps/${ids.gapId}/`)
        && request.method() === "POST") {
      const operation = path.split("/").at(-1);
      const body = request.postDataJSON() as Record<string, string>;
      const from = gap.lifecycle;
      if (operation === "triage") gap.lifecycle = "triaged";
      if (operation === "assign") {
        gap.lifecycle = "assigned";
        gap.owner = body.owner_subject_id;
        gap.due = "2026-08-03T00:00:00Z";
      }
      if (operation === "answer") {
        gap.lifecycle = "answered";
        gap.resolving = body.resolving_version_id;
      }
      if (operation === "decline") gap.lifecycle = "declined";
      gap.transitions.push({
        from_state: from, to_state: gap.lifecycle, reason: body.reason,
      });
      return route.fulfill({json: gapJson()});
    }
    if (path === "/api/governance/research/packages") {
      return route.fulfill({json: {items: [{
        zone_label: "research", package_id: ids.packageId,
        source_key: "refinery.industry", fingerprint: sha, payload_sha256: sha,
        captured_at: "2026-07-01T00:00:00Z",
        snapshot_scope: "industry-vn-2026", adapter_version: "refinery-1.2",
        tier_composition: {P: 1}, import_state: "imported",
        rejection_code: null, record_count: 1,
        received_at: "2026-07-02T00:00:00Z",
        imported_at: "2026-07-02T00:01:00Z",
      }], next_cursor: null}});
    }
    if (path === `/api/governance/research/packages/${ids.packageId}/records`) {
      return route.fulfill({json: {items: [researchRecord], next_cursor: null}});
    }
    if (path === `/api/governance/research/records/${ids.recordId}`) {
      return route.fulfill({json: researchRecord});
    }
    if (path === "/api/governance/graduation/proposals") {
      return route.fulfill({json: {items: [proposalJson()], next_cursor: null}});
    }
    if (path === `/api/governance/graduation/proposals/${ids.proposalId}`) {
      return route.fulfill({json: proposalJson()});
    }
    return route.fulfill({status: 404, json: {
      error: {code: "not_found", message: ""}, request_id: "req-0",
    }});
  });
}
