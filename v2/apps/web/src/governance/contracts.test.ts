import {describe, expect, test} from "vitest";
import {
  parseDashboard,
  parseGapDetail,
  parseGapPage,
  parseProposal,
  parseQueuePage,
  parseResearchPackagePage,
  parseResearchRecord,
  parseTypedError,
  parseWorkspaceState,
  workspaceQuery,
} from "./contracts";

const sha = "a".repeat(64);
const id = (n: string) => `${n.repeat(8)}-${n.repeat(4)}-4${n.repeat(3)}-8${n.repeat(3)}-${n.repeat(12)}`;

const dashboard = {
  computed_at: "2026-08-01T00:00:00Z",
  coverage: {zone_label: "sot", total_records: 12, by_source_key: {kernel: 12},
    by_owner: {curator: 12}, by_classification: {internal: 10, restricted: 2}},
  freshness: {zone_label: "sot", total: 3, expiring: 2, expired: 1, assigned: 1, unassigned: 2},
  conflict: {zone_label: "sot", total: 2, disputed: 1, superseded_ambiguous: 1,
    assigned: 1, unassigned: 1},
  owner_review: {zone_label: "sot", total: 4, due: 3, overdue: 1,
    assigned: 2, unassigned: 2},
  gap_flow: {zone_label: "sot", open_total: 4, closed_total: 6, overdue: 1,
    by_state: {open: 3, triaged: 1}, aging: {under_24h: 2, days_1_3: 2}},
  research_intake: {zone_label: "research", sources_total: 2, sources_active: 1,
    packages_by_state: {imported: 3, rejected: 1}, records_by_tier: {P: 5, S: 2}},
  graduation: {zone_label: "research", proposed: 2, approved: 1, rejected: 1, submitted: 1},
};

const researchRecord = {
  zone_label: "research", research_record_id: id("1"), package_id: id("2"),
  package_fingerprint: sha, source_key: "refinery.industry",
  record_key: "vendor.abb.profile", version_ordinal: 1, tier: "P",
  content: {name: "ABB"}, searchable_text: "ABB robotics",
  evidence: [{source_url: "https://example.com/a", locator: {page: 1},
    quoted_text: "ABB manufactures robots.", checksum: sha}],
  corroboration_state: "corroborated", content_sha256: sha,
  created_at: "2026-07-30T00:00:00Z",
};

const gap = {
  gap_id: id("3"), question_fingerprint: sha,
  sanitized_question: "Chính sách bảo hành robot?",
  sanitized_summary: "Bảo hành robot", reason_category: "no_evidence",
  classification: "internal", requester_id: id("4"), owner_subject_id: null,
  routing_key: "governance.gap", occurrence_count: 2, lifecycle: "open",
  origin: "honest_null", priority: "high",
  first_seen_at: "2026-07-29T00:00:00Z", last_seen_at: "2026-07-31T00:00:00Z",
  triaged_at: null, assigned_at: null, due_at: null, answered_at: null,
  closed_at: null, resolving_version_id: null, decline_reason: null,
};

describe("zone label unforgeability at the client edge", () => {
  test("research payloads parse only with the exact research zone label", () => {
    expect(parseResearchRecord(researchRecord).zone_label).toBe("research");
  });

  test.each([
    ["missing zone label", Object.fromEntries(
      Object.entries(researchRecord).filter(([key]) => key !== "zone_label"),
    )],
    ["forged SOT label", {...researchRecord, zone_label: "sot"}],
    ["forged private label", {...researchRecord, zone_label: "private"}],
    ["empty label", {...researchRecord, zone_label: ""}],
  ])("rejects research record with %s", (_label, value) => {
    expect(() => parseResearchRecord(value)).toThrow("zone_label_forged");
  });

  test("package pages reject any forged member atomically", () => {
    const item = {
      zone_label: "research", package_id: id("5"), source_key: "refinery.industry",
      fingerprint: sha, payload_sha256: sha, captured_at: "2026-07-01T00:00:00Z",
      snapshot_scope: "industry-vn", adapter_version: "refinery-1.2",
      tier_composition: {P: 3}, import_state: "imported", rejection_code: null,
      record_count: 3, received_at: "2026-07-02T00:00:00Z",
      imported_at: "2026-07-02T00:01:00Z",
    };
    expect(parseResearchPackagePage({items: [item], next_cursor: null}).items).toHaveLength(1);
    expect(() => parseResearchPackagePage({
      items: [item, {...item, zone_label: "sot"}], next_cursor: null,
    })).toThrow("zone_label_forged");
  });

  test("dashboard tiles must carry their server-declared zones", () => {
    const parsed = parseDashboard(dashboard);
    expect(parsed.gap_flow.zone_label).toBe("sot");
    expect(parsed.research_intake.zone_label).toBe("research");
    expect(parsed.conflict.zone_label).toBe("sot");
    expect(parsed.conflict.disputed).toBe(1);
    expect(parsed.owner_review.zone_label).toBe("sot");
    expect(parsed.owner_review.overdue).toBe(1);
    expect(() => parseDashboard({
      ...dashboard, research_intake: {...dashboard.research_intake, zone_label: "sot"},
    })).toThrow("zone_label_forged");
    expect(() => parseDashboard({
      ...dashboard, coverage: {...dashboard.coverage, zone_label: "research"},
    })).toThrow("invalid_tile_zone");
    expect(() => parseDashboard({
      ...dashboard, conflict: {...dashboard.conflict, zone_label: "research"},
    })).toThrow("invalid_tile_zone");
  });

  test("gap and queue payloads gate the literal SOT zone label (AC-07)", () => {
    // Absent label (older shape) parses with no chip; the literal parses;
    // any other value is forged and rejects the payload.
    expect(parseGapPage({items: [gap], next_cursor: null})
      .items[0].zone_label).toBeNull();
    expect(parseGapPage({items: [{...gap, zone_label: "sot"}], next_cursor: null})
      .items[0].zone_label).toBe("sot");
    expect(() => parseGapPage({
      items: [{...gap, zone_label: "research"}], next_cursor: null,
    })).toThrow("zone_label_forged");
    expect(() => parseGapPage({
      items: [{...gap, zone_label: "SOT"}], next_cursor: null,
    })).toThrow("zone_label_forged");
  });
});

describe("governance payload contracts", () => {
  test("parses gaps, transitions and rejects hostile fields", () => {
    const page = parseGapPage({items: [gap], next_cursor: "cursor-1"});
    expect(page.items[0].priority).toBe("high");
    expect(page.next_cursor).toBe("cursor-1");
    expect(() => parseGapPage({items: [{...gap, lifecycle: "erased"}]}))
      .toThrow("invalid_gap");
    expect(() => parseGapPage({items: [{...gap, gap_id: "../../etc"}]}))
      .toThrow("invalid_gap");
    const detail = parseGapDetail({gap, transitions: [{
      sequence: 1, transition_id: id("6"), gap_id: gap.gap_id,
      from_state: "open", to_state: "triaged", actor_subject_id: id("4"),
      reason: "Nhận xử lý", occurred_at: "2026-07-31T01:00:00Z",
    }]});
    expect(detail.transitions[0].to_state).toBe("triaged");
    expect(() => parseGapDetail({gap, transitions: [{}]}))
      .toThrow("invalid_gap_transition");
  });

  test("parses live queue pages with conflict sides and assignment tasks", () => {
    const page = parseQueuePage({
      zone_label: "sot",
      queue_kind: "conflict", computed_at: "2026-08-01T00:00:00Z",
      entries: [{
        zone_label: "sot",
        queue_kind: "conflict", record_id: id("1"), record_key: "company.name",
        record_version_id: id("2"), owner_subject_id: id("4"),
        classification: "internal", status: "disputed",
        sort_at: "2026-08-01T00:00:00Z", effective_to: null, review_due_at: null,
        sides: [{version_id: id("2"), record_id: id("1"), package_revision: 3,
          provenance_level: "verified_primary", verification_state: "attested",
          content_sha256: sha, evidence_refs: ["evidence/a.pdf"],
          effective_from: "2026-07-01T00:00:00Z", external: false}],
        task: {task_id: id("7"), queue_kind: "conflict", record_version_id: id("2"),
          assignee_subject_id: id("4"), assigned_by: id("4"), state: "assigned",
          due_at: null, note: "", created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z", completed_at: null},
      }],
      aggregates: {total: 1, by_status: {disputed: 1}, assigned: 1, unassigned: 0},
      next_cursor: null,
    });
    expect(page.entries[0].sides[0].provenance_level).toBe("verified_primary");
    expect(page.zone_label).toBe("sot");
    expect(page.entries[0].zone_label).toBe("sot");
    expect(page.aggregates.assigned).toBe(1);
    expect(() => parseQueuePage({
      queue_kind: "conflict", computed_at: "2026-08-01T00:00:00Z",
      entries: [], aggregates: {total: -1, by_status: {}, assigned: 0, unassigned: 0},
    })).toThrow("invalid_queue_aggregates");
  });

  test("parses graduation proposals and rejects unknown states", () => {
    const proposal = {
      proposal_id: id("8"), research_record_ids: [id("1")],
      claim_draft: {claim_text: "ABB là đối tác", classification: "internal"},
      target_record_key: "partners.abb", proposer_subject_id: id("4"),
      rationale: "Đủ bằng chứng tier P", state: "approved", decided_by: id("5"),
      decision_reason: "Hợp lệ", attestation_hash: sha,
      publish_package_id: id("9"), supersedes_proposal_id: null,
      proposed_at: "2026-07-30T00:00:00Z", decided_at: "2026-07-31T00:00:00Z",
    };
    expect(parseProposal(proposal).publish_package_id).toBe(id("9"));
    expect(() => parseProposal({...proposal, state: "activated"}))
      .toThrow("invalid_proposal");
  });

  test("typed error envelopes degrade safely", () => {
    expect(parseTypedError({
      error: {code: "curator_required", message: "x"}, request_id: "req-9",
    })).toEqual({code: "curator_required", message: "x", requestId: "req-9"});
    expect(parseTypedError("garbage", "fallback").code).toBe("unknown_error");
    expect(parseTypedError(null).requestId).toBe("");
  });
});

describe("URL-restorable workspace state", () => {
  test("round-trips valid state without restricted metadata", () => {
    const state = parseWorkspaceState(new URLSearchParams(
      `view=graduation&proposal=${id("8")}&state=open&priority=high`,
    ));
    expect(state.view).toBe("graduation");
    expect(state.proposalId).toBe(id("8"));
    expect(workspaceQuery(state)).toContain("proposal=");
  });

  test("drops hostile params and unknown views", () => {
    const state = parseWorkspaceState(new URLSearchParams(
      "view=__proto__&gap=..%2F..&record=<script>&state=erased&priority=root",
    ));
    expect(state).toEqual({view: "dashboard"});
    expect(workspaceQuery(state)).toBe("");
  });
});
