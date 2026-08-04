import {expect, test} from "vitest";
import {parseJobHealth, parsePilotReadiness, parseResearchSources, parseSettings, parseSubjects} from "./contracts";

const pilot = {
  computed_at: "2026-08-04T00:00:00Z",
  sot: {active_records: 219, strict_records: 8, caveated_records: 211,
    current_records: 219, stale_records: 0, named_owner_records: 0,
    placeholder_owner_records: 219, caveated_named_owner_records: 0,
    caveated_placeholder_owner_records: 211, high_risk_records: 20,
    high_risk_caveated_records: 12, zone_masquerade_findings: 0},
  files: {documents: 30, versions: 30, representative_versions: 30,
    ready_versions: 30, indexed_versions: 30, viewer_families: {pdf: 8, docx: 8, xlsx: 7, image: 7},
    original_checksum_mismatches: 0, rendition_lineage_mismatches: 0},
  templates: {templates: 4, approved_templates: 4, locked_bindings: 10, official_or_legal_approved: 0},
  research: {active_sources: 1, imported_packages: 1, records: 70,
    tiers: {P: 70}, corroboration: {corroborated: 16, disputed: 24, uncorroborated: 30}},
  question_count: 32,
  gates: [{gate_key: "sot_gold_baseline", target: 8, actual: 8, state: "met", detail: "retained"}],
  production_boundary: "local_dev_only",
};

test("admin parsers accept bounded backend payloads", () => {
  expect(parseResearchSources([])).toEqual([]); expect(parseSubjects([])).toEqual([]); expect(parseSettings([])).toEqual([]);
  expect(parseJobHealth({computed_at: "2026-08-04T00:00:00Z", families: [{family: "ingestion", job_counts: {done: 1}, outbox_counts: {}, recent_failures: []}]}).families[0].family).toBe("ingestion");
  expect(parsePilotReadiness(pilot).research.records).toBe(70);
});

test.each([
  () => parseResearchSources([{source_id: "not-a-uuid"}]),
  () => parseSubjects([{user_id: "not-a-uuid"}]),
  () => parseSettings([{setting_key: "x", value_type: "executable"}]),
  () => parseSettings([{setting_key: "x", value_type: "integer", description: "x", minimum: "0", maximum: null, default: 1, value: 1, version: 0, updated_at: null}]),
  () => parseJobHealth({computed_at: "today", families: []}),
  () => parseJobHealth({computed_at: "2026-08-04T00:00:00Z", families: [{family: "truth-writer", job_counts: {}, outbox_counts: {}, recent_failures: []}]}),
  () => parsePilotReadiness({...pilot, production_boundary: "production"}),
  () => parsePilotReadiness({...pilot, question_count: -1}),
])("malformed or expanded admin contracts fail closed", parse => {
  expect(parse).toThrow("contract_violation");
});
