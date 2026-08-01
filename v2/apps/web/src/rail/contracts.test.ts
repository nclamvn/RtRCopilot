import {describe, expect, test} from "vitest";
import {
  evidenceFromAskCitation,
  evidenceFromResearchHit,
  evidenceHref,
  parseObjectLocator,
  parseResearchSearchEvidence,
  railEntryId,
} from "./contracts";

const versionId = "22222222-2222-4222-8222-222222222222";
const sha = "a".repeat(64);

const citation = {
  marker: "C1",
  chunk_id: "11111111-1111-4111-8111-111111111111",
  record_key: "company.warranty",
  record_version_id: versionId,
  evidence_key: "company.warranty.e1",
  record_checksum: sha,
  evidence_checksum: "b".repeat(64),
  source_key: "rtr.specs",
  source_revision: 3,
  provenance_level: "approved_internal",
  verification_state: "approved",
  freshness_state: "current",
  source_label: "Company specification",
  locator: {page: 4},
  redacted: false,
};

const researchHit = {
  zone_label: "research",
  research_record_id: "33333333-3333-4333-8333-333333333333",
  record_key: "vendor.abb.profile",
  tier: "P",
  snippet: "ABB manufactures industrial robots.",
  lexical_score: 0.8,
  citation: {
    zone_label: "research",
    research_record_id: "33333333-3333-4333-8333-333333333333",
    record_key: "vendor.abb.profile",
    version_ordinal: 1,
    tier: "P",
    source_key: "refinery.industry",
    package_fingerprint: sha,
    content_sha256: "c".repeat(64),
    corroboration_state: "corroborated",
    evidence_checksums: ["d".repeat(64)],
  },
};

describe("ask citation adapter", () => {
  test("parses a valid TIP-007 citation with no zone label and a typed locator", () => {
    const entry = evidenceFromAskCitation(citation, "grounded");
    expect(entry.key).toBe("C1");
    expect(entry.marker).toBe("C1");
    // Absent server label (pre-TIP-011 payload shape) → no chip, no guess.
    expect(entry.zone).toBeNull();
    expect(entry.grounding).toBe("grounded");
    expect(entry.sourceKey).toBe("rtr.specs");
    expect(entry.sourceRevision).toBe(3);
    expect(entry.recordVersionId).toBe(versionId);
    expect(entry.recordChecksum).toBe(sha);
    expect(entry.evidenceChecksums).toEqual(["b".repeat(64)]);
    expect(entry.freshnessState).toBe("current");
    expect(entry.verificationState).toBe("approved");
    expect(entry.redacted).toBe(false);
    expect(entry.locator).toEqual({page: 4});
  });

  test("the literal server sot label renders the chip; any other label is forged", () => {
    const labeled = evidenceFromAskCitation(
      {...citation, zone_label: "sot"},
      "grounded",
    );
    expect(labeled.zone).toBe("sot");
    expect(() => evidenceFromAskCitation({...citation, zone_label: "research"}, "grounded"))
      .toThrow("zone_label_forged");
    expect(() => evidenceFromAskCitation({...citation, zone_label: "private"}, "grounded"))
      .toThrow("zone_label_forged");
    expect(() => evidenceFromAskCitation({...citation, zone_label: "SOT"}, "grounded"))
      .toThrow("zone_label_forged");
  });

  test.each([
    {patch: {marker: "X1"}}, {patch: {marker: "[C1]"}},
    {patch: {record_version_id: "not-a-uuid"}},
    {patch: {record_checksum: "short"}},
    {patch: {redacted: "yes"}},
    {patch: {locator: "page-4"}},
  ])("rejects malformed citation $patch", ({patch}) => {
    expect(() => evidenceFromAskCitation({...citation, ...patch}, "grounded")).toThrow();
  });
});

describe("research evidence adapter — forged-zone regression", () => {
  test("parses a valid research hit with the exact server research label", () => {
    const entry = evidenceFromResearchHit(researchHit);
    expect(entry.zone).toBe("research");
    expect(entry.grounding).toBe("research_supported");
    expect(entry.tier).toBe("P");
    expect(entry.corroborationState).toBe("corroborated");
    expect(entry.contentChecksum).toBe("c".repeat(64));
    expect(entry.evidenceChecksums).toEqual(["d".repeat(64)]);
    expect(entry.recordVersionId).toBeNull();
    expect(entry.snippet).toContain("ABB");
  });

  test("zone_label \"sot\" on research-shaped evidence refuses to render", () => {
    expect(() => evidenceFromResearchHit({...researchHit, zone_label: "sot"}))
      .toThrow("zone_label_forged");
    expect(() => evidenceFromResearchHit({
      ...researchHit,
      citation: {...researchHit.citation, zone_label: "sot"},
    })).toThrow("zone_label_forged");
  });

  test("a missing zone label refuses to render", () => {
    const unlabeled: Record<string, unknown> = {...researchHit};
    delete unlabeled.zone_label;
    expect(() => evidenceFromResearchHit(unlabeled)).toThrow("zone_label_forged");
  });

  test("response-level zone and grounding constants are gated", () => {
    const response = {
      zone_label: "research", grounding: "research_supported",
      results: [researchHit], request_id: "req-1",
    };
    const parsed = parseResearchSearchEvidence(response);
    expect(parsed.zone).toBe("research");
    expect(parsed.grounding).toBe("research_supported");
    expect(parsed.entries).toHaveLength(1);
    expect(() => parseResearchSearchEvidence({...response, zone_label: "sot"}))
      .toThrow("zone_label_forged");
    expect(() => parseResearchSearchEvidence({...response, grounding: "sot_grounded"}))
      .toThrow("invalid_research_search");
  });
});

describe("locator parsing and deep links", () => {
  test("keeps bounded rtr.locator.v1 members and drops hostile values", () => {
    expect(parseObjectLocator({page: 4, line: 12})).toEqual({page: 4});
    expect(parseObjectLocator({page: 0})).toBeNull();
    expect(parseObjectLocator({page: 1e9})).toBeNull();
    expect(parseObjectLocator({sheet: "Doanh thu", cell: "b7"}))
      .toEqual({sheet: "Doanh thu", cell: "B7"});
    expect(parseObjectLocator({cell: "TOOLONG123456"})).toBeNull();
    expect(parseObjectLocator({slide: 3, shape: 2})).toEqual({slide: 3, shape: 2});
    expect(parseObjectLocator({t: 12_500})).toEqual({t: 12_500});
    expect(parseObjectLocator({t: 99_999_999})).toBeNull();
    expect(parseObjectLocator({selector: "p:nth-of-type(4)"})).toBeNull();
    expect(parseObjectLocator({paragraph: 2})).toEqual({paragraph: 2});
    expect(parseObjectLocator({region: "p1-r1"})).toEqual({region: "p1-r1"});
    expect(parseObjectLocator({region: "../../etc"})).toBeNull();
    expect(parseObjectLocator("page=4")).toBeNull();
  });

  test("evidenceHref follows the TIP-008 file deep-link contract", () => {
    const entry = evidenceFromAskCitation(citation, "grounded");
    expect(evidenceHref(entry)).toBe(`/files?version=${versionId}&page=4`);
    const research = evidenceFromResearchHit(researchHit);
    expect(evidenceHref(research)).toBeNull();
  });

  test("rail entry ids stay DOM-safe", () => {
    expect(railEntryId("C1")).toBe("rail-entry-C1");
    expect(railEntryId("research-33333333")).toBe("rail-entry-research-33333333");
    expect(railEntryId("a b<c>")).toBe("rail-entry-a_b_c_");
  });
});
