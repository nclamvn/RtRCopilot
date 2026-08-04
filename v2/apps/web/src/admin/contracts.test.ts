import {expect, test} from "vitest";
import {parseJobHealth, parseResearchSources, parseSettings, parseSubjects} from "./contracts";

test("admin parsers accept bounded backend payloads", () => {
  expect(parseResearchSources([])).toEqual([]); expect(parseSubjects([])).toEqual([]); expect(parseSettings([])).toEqual([]);
  expect(parseJobHealth({computed_at: "2026-08-04T00:00:00Z", families: [{family: "ingestion", job_counts: {done: 1}, outbox_counts: {}, recent_failures: []}]}).families[0].family).toBe("ingestion");
});

test.each([
  () => parseResearchSources([{source_id: "not-a-uuid"}]),
  () => parseSubjects([{user_id: "not-a-uuid"}]),
  () => parseSettings([{setting_key: "x", value_type: "executable"}]),
  () => parseSettings([{setting_key: "x", value_type: "integer", description: "x", minimum: "0", maximum: null, default: 1, value: 1, version: 0, updated_at: null}]),
  () => parseJobHealth({computed_at: "today", families: []}),
  () => parseJobHealth({computed_at: "2026-08-04T00:00:00Z", families: [{family: "truth-writer", job_counts: {}, outbox_counts: {}, recent_failures: []}]}),
])("malformed or expanded admin contracts fail closed", parse => {
  expect(parse).toThrow("contract_violation");
});
