import {describe, expect, it} from "vitest";
import {parseIntelligenceBriefing} from "./contracts";

const id = "8f589e87-7f79-4ae4-9ac0-f874a56ef196";
const sha = "a".repeat(64);

function response() {
  return {
    generated_at: "2026-08-15T05:00:00Z",
    request_id: "req-038",
    counts: {updates: 1, attention: 0, research: 0},
    items: [{
      item_id: sha,
      zone_label: "sot",
      kind: "update",
      priority: "normal",
      title: "HERA roadmap",
      summary: "Roadmap đã được phê duyệt.",
      observed_at: "2026-08-15T04:00:00Z",
      ask_query: "Giải thích tác động của roadmap HERA.",
      evidence: {
        zone_label: "sot",
        record_key: "RTR.HERA.ROADMAP",
        source_key: "rtr.company",
        source_label: "Company registry",
        content_sha256: sha,
        locator: {record_key: "RTR.HERA.ROADMAP"},
        record_version_id: id,
        source_revision: 2,
        provenance_level: "approved_internal",
        verification_state: "approved",
        freshness_state: "current",
        research_record_id: null,
        package_fingerprint: null,
        tier: null,
        corroboration_state: null,
      },
    }],
  };
}

describe("intelligence contracts", () => {
  it("parses a strict SOT briefing", () => {
    const parsed = parseIntelligenceBriefing(response());
    expect(parsed.items[0].evidence.recordVersionId).toBe(id);
    expect(parsed.counts.updates).toBe(1);
  });

  it("rejects mismatched aggregate counts", () => {
    const value = response();
    value.counts.updates = 2;
    expect(() => parseIntelligenceBriefing(value)).toThrow("invalid_intelligence_briefing");
  });

  it("rejects a research identity disguised as SOT", () => {
    const original = response();
    const value = {
      ...original,
      items: original.items.map((item, index) => index === 0 ? {
        ...item,
        evidence: {
          ...item.evidence,
          record_version_id: null,
          research_record_id: id,
        },
      } : item),
    };
    expect(() => parseIntelligenceBriefing(value)).toThrow("invalid_intelligence_evidence");
  });

  it("requires the complete immutable identity for each trust zone", () => {
    const original = response();
    const missingRevision = {
      ...original,
      items: original.items.map(item => ({
        ...item,
        evidence: {...item.evidence, source_revision: null},
      })),
    };
    expect(() => parseIntelligenceBriefing(missingRevision))
      .toThrow("invalid_intelligence_evidence");

    const mixedFingerprint = {
      ...original,
      items: original.items.map(item => ({
        ...item,
        evidence: {...item.evidence, package_fingerprint: sha},
      })),
    };
    expect(() => parseIntelligenceBriefing(mixedFingerprint))
      .toThrow("invalid_intelligence_evidence");
  });
});
