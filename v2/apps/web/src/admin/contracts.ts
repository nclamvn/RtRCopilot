export type Classification = "public_internal" | "internal" | "restricted" | "highly_restricted";
export type SourceLifecycle = "active" | "suspended" | "retired";
export type SourceOrigin = "refinery" | "manual" | "partner";
export type SettingValueType = "integer" | "decimal" | "boolean" | "string" | "duration_hours";
export type SettingValue = number | boolean | string;

export type ResearchSource = {
  source_id: string; stable_key: string; display_name: string; description: string;
  origin: SourceOrigin; owner_subject_id: string; classification: Classification;
  lifecycle: SourceLifecycle; created_at: string; updated_at: string;
};
export type SubjectAccount = {
  user_id: string; issuer: string; email: string | null; display_name: string;
  status: string; security_version: number; roles: string[]; groups: string[];
  last_seen_at: string;
};
export type SettingView = {
  setting_key: string; value_type: SettingValueType; description: string;
  minimum: number | null; maximum: number | null; default: SettingValue;
  value: SettingValue; version: number; updated_at: string | null;
};
export type SettingVersion = {
  setting_id: string; setting_key: string; version: number;
  value_type: SettingValueType; value: SettingValue; updated_by: string;
  reason: string; created_at: string;
};
export type JobFailure = {
  job_id: string; kind: string; status: string; error_code: string | null;
  attempt: number | null; occurred_at: string;
};
export type JobFamily = {
  family: "ingestion" | "render" | "reindex"; job_counts: Record<string, number>;
  outbox_counts: Record<string, number>; recent_failures: JobFailure[];
};
export type JobHealth = {computed_at: string; families: JobFamily[]};
export type PilotGateState = "met" | "partial" | "blocked";
export type PilotReadiness = {
  computed_at: string;
  sot: {
    active_records: number; strict_records: number; caveated_records: number;
    current_records: number; stale_records: number; named_owner_records: number;
    placeholder_owner_records: number; caveated_named_owner_records: number;
    caveated_placeholder_owner_records: number; high_risk_records: number;
    high_risk_caveated_records: number; zone_masquerade_findings: number;
  };
  files: {
    documents: number; versions: number; representative_versions: number;
    ready_versions: number; indexed_versions: number;
    viewer_families: Record<string, number>;
    original_checksum_mismatches: number; rendition_lineage_mismatches: number;
  };
  templates: {
    templates: number; approved_templates: number; locked_bindings: number;
    official_or_legal_approved: number;
  };
  research: {
    active_sources: number; imported_packages: number; records: number;
    tiers: Record<string, number>; corroboration: Record<string, number>;
  };
  question_count: number;
  gates: Array<{
    gate_key: string; target: number; actual: number;
    state: PilotGateState; detail: string;
  }>;
  production_boundary: "local_dev_only";
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CLASSIFICATIONS = new Set(["public_internal", "internal", "restricted", "highly_restricted"]);
const LIFECYCLES = new Set(["active", "suspended", "retired"]);
const ORIGINS = new Set(["refinery", "manual", "partner"]);
const VALUE_TYPES = new Set(["integer", "decimal", "boolean", "string", "duration_hours"]);
const FAMILIES = new Set(["ingestion", "render", "reindex"]);
const PILOT_GATE_STATES = new Set(["met", "partial", "blocked"]);

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("contract_violation");
  return value as Record<string, unknown>;
}
function string(value: unknown, max = 10_000): string {
  if (typeof value !== "string" || value.length > max) throw new Error("contract_violation");
  return value;
}
function uuid(value: unknown): string {
  const result = string(value, 64); if (!UUID.test(result)) throw new Error("contract_violation"); return result;
}
function stamp(value: unknown): string {
  const result = string(value, 64); if (Number.isNaN(Date.parse(result))) throw new Error("contract_violation"); return result;
}
function integer(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) throw new Error("contract_violation"); return Number(value);
}
function finiteNumber(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("contract_violation");
  return value;
}
function nullable<T>(value: unknown, parse: (item: unknown) => T): T | null {
  return value === null ? null : parse(value);
}
function choice<T extends string>(value: unknown, choices: Set<string>): T {
  const result = string(value, 128); if (!choices.has(result)) throw new Error("contract_violation"); return result as T;
}
function value(value_: unknown): SettingValue {
  if (typeof value_ !== "string" && typeof value_ !== "number" && typeof value_ !== "boolean") throw new Error("contract_violation");
  if (typeof value_ === "number" && !Number.isFinite(value_)) throw new Error("contract_violation");
  return value_;
}
function countMap(value_: unknown): Record<string, number> {
  const item = object(value_); const result: Record<string, number> = {};
  if (Object.keys(item).length > 100) throw new Error("contract_violation");
  for (const [key, entry] of Object.entries(item)) result[string(key, 128)] = integer(entry);
  return result;
}

export function parseResearchSource(value_: unknown): ResearchSource {
  const v = object(value_);
  return {source_id: uuid(v.source_id), stable_key: string(v.stable_key, 128),
    display_name: string(v.display_name, 200), description: string(v.description, 2000),
    origin: choice<SourceOrigin>(v.origin, ORIGINS), owner_subject_id: uuid(v.owner_subject_id),
    classification: choice<Classification>(v.classification, CLASSIFICATIONS),
    lifecycle: choice<SourceLifecycle>(v.lifecycle, LIFECYCLES), created_at: stamp(v.created_at),
    updated_at: stamp(v.updated_at)};
}
export function parseResearchSources(value_: unknown) {
  if (!Array.isArray(value_) || value_.length > 1000) throw new Error("contract_violation");
  return value_.map(parseResearchSource);
}
export function parseSubject(value_: unknown): SubjectAccount {
  const v = object(value_); const roles = v.roles; const groups = v.groups;
  if (!Array.isArray(roles) || !Array.isArray(groups)) throw new Error("contract_violation");
  return {user_id: uuid(v.user_id), issuer: string(v.issuer, 512),
    email: nullable(v.email, item => string(item, 320)), display_name: string(v.display_name, 300),
    status: string(v.status, 64), security_version: integer(v.security_version),
    roles: roles.map(item => string(item, 128)), groups: groups.map(item => string(item, 128)),
    last_seen_at: stamp(v.last_seen_at)};
}
export function parseSubjects(value_: unknown) {
  if (!Array.isArray(value_) || value_.length > 200) throw new Error("contract_violation");
  return value_.map(parseSubject);
}
export function parseSetting(value_: unknown): SettingView {
  const v = object(value_);
  return {setting_key: string(v.setting_key, 128), value_type: choice<SettingValueType>(v.value_type, VALUE_TYPES),
    description: string(v.description, 2000), minimum: nullable(v.minimum, finiteNumber),
    maximum: nullable(v.maximum, finiteNumber), default: value(v.default), value: value(v.value),
    version: integer(v.version), updated_at: nullable(v.updated_at, stamp)};
}
export function parseSettings(value_: unknown) {
  if (!Array.isArray(value_) || value_.length > 500) throw new Error("contract_violation");
  return value_.map(parseSetting);
}
export function parseSettingVersion(value_: unknown): SettingVersion {
  const v = object(value_);
  return {setting_id: uuid(v.setting_id), setting_key: string(v.setting_key, 128), version: integer(v.version),
    value_type: choice<SettingValueType>(v.value_type, VALUE_TYPES), value: value(v.value),
    updated_by: uuid(v.updated_by), reason: string(v.reason, 2000), created_at: stamp(v.created_at)};
}
export function parseSettingVersions(value_: unknown) {
  if (!Array.isArray(value_) || value_.length > 1000) throw new Error("contract_violation");
  return value_.map(parseSettingVersion);
}
export function parseJobHealth(value_: unknown): JobHealth {
  const v = object(value_); if (!Array.isArray(v.families) || v.families.length > 3) throw new Error("contract_violation");
  return {computed_at: stamp(v.computed_at), families: v.families.map(item_ => {
    const item = object(item_); if (!Array.isArray(item.recent_failures)) throw new Error("contract_violation");
    return {family: choice<JobFamily["family"]>(item.family, FAMILIES), job_counts: countMap(item.job_counts),
      outbox_counts: countMap(item.outbox_counts), recent_failures: item.recent_failures.map(failure_ => {
        const failure = object(failure_); return {job_id: uuid(failure.job_id), kind: string(failure.kind, 128),
          status: string(failure.status, 128), error_code: nullable(failure.error_code, entry => string(entry, 128)),
          attempt: nullable(failure.attempt, integer), occurred_at: stamp(failure.occurred_at)};
      })};
  })};
}

export function parsePilotReadiness(value_: unknown): PilotReadiness {
  const v = object(value_); const sot = object(v.sot); const files = object(v.files);
  const templates = object(v.templates); const research = object(v.research);
  if (!Array.isArray(v.gates) || v.gates.length > 50) throw new Error("contract_violation");
  const boundary = string(v.production_boundary, 64);
  if (boundary !== "local_dev_only") throw new Error("contract_violation");
  return {
    computed_at: stamp(v.computed_at),
    sot: {
      active_records: integer(sot.active_records), strict_records: integer(sot.strict_records),
      caveated_records: integer(sot.caveated_records), current_records: integer(sot.current_records),
      stale_records: integer(sot.stale_records), named_owner_records: integer(sot.named_owner_records),
      placeholder_owner_records: integer(sot.placeholder_owner_records),
      caveated_named_owner_records: integer(sot.caveated_named_owner_records),
      caveated_placeholder_owner_records: integer(sot.caveated_placeholder_owner_records),
      high_risk_records: integer(sot.high_risk_records),
      high_risk_caveated_records: integer(sot.high_risk_caveated_records),
      zone_masquerade_findings: integer(sot.zone_masquerade_findings),
    },
    files: {
      documents: integer(files.documents), versions: integer(files.versions),
      representative_versions: integer(files.representative_versions),
      ready_versions: integer(files.ready_versions), indexed_versions: integer(files.indexed_versions),
      viewer_families: countMap(files.viewer_families),
      original_checksum_mismatches: integer(files.original_checksum_mismatches),
      rendition_lineage_mismatches: integer(files.rendition_lineage_mismatches),
    },
    templates: {
      templates: integer(templates.templates),
      approved_templates: integer(templates.approved_templates),
      locked_bindings: integer(templates.locked_bindings),
      official_or_legal_approved: integer(templates.official_or_legal_approved),
    },
    research: {
      active_sources: integer(research.active_sources),
      imported_packages: integer(research.imported_packages),
      records: integer(research.records), tiers: countMap(research.tiers),
      corroboration: countMap(research.corroboration),
    },
    question_count: integer(v.question_count),
    gates: v.gates.map(gate_ => { const gate = object(gate_); return {
      gate_key: string(gate.gate_key, 128), target: integer(gate.target), actual: integer(gate.actual),
      state: choice<PilotGateState>(gate.state, PILOT_GATE_STATES), detail: string(gate.detail, 1000),
    };}),
    production_boundary: boundary,
  };
}
