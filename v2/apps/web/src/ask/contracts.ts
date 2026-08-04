/**
 * Typed contracts for the Ask workspace (TIP-011 Task 2, D-011-03).
 *
 * The TIP-007 answer API is consumed as-is: `state` is the server grounding
 * metadata (`grounded` SOT facts, `honest_null` with a recorded gap id,
 * `failed`), citations adapt into the shared Evidence Rail contract through
 * `evidenceFromAskCitation` (which enforces the client-edge zone gate), and
 * the conversation id is URL-restorable with no restricted metadata in
 * browser storage.
 */

import {ViewerKind} from "../files/contracts";
import {EvidenceEntry, evidenceFromAskCitation} from "../rail/contracts";

export type AnswerState = "grounded" | "honest_null" | "failed";
export type AnswerReason =
  | "no_evidence"
  | "denied_or_unavailable"
  | "insufficient_confidence"
  | "stale_only"
  | "grounding_failed"
  | "manual_entry"
  | "answer_quality_configuration_required";

export type AskAnswer = {
  state: AnswerState;
  answer: string;
  entries: EvidenceEntry[];
  conversationId: string;
  answerRunId: string;
  gapId: string | null;
  answerMode: "quality_llm" | "evidence_only" | null;
  /** Typed abstention reason; configuration failures are not knowledge gaps. */
  reasonCode: AnswerReason | null;
  /**
   * TIP-013B AC-4: true only when the backend grounded this answer on at
   * least one softly-verified fact (server `confidence_caveat`). The Ask
   * surface then shows the double-check caveat line. Absent on older payloads
   * and never set on non-grounded answers.
   */
  confidenceCaveat: boolean;
  requestId: string;
};

export type ConversationMessage = {
  messageId: string;
  role: "user" | "assistant";
  content: string;
  answerState: string | null;
  entries: EvidenceEntry[];
  createdAt: string;
};

export type Conversation = {
  conversationId: string;
  messages: ConversationMessage[];
  requestId: string;
};

/** One row of the caller's own conversation list (TIP-011 backend). */
export type ConversationSummary = {
  conversationId: string;
  startedAt: string;
  lastActivityAt: string;
  /** First user message's stored content digest — never message content. */
  firstQuestionDigest: string | null;
};

export type ConversationListPage = {
  items: ConversationSummary[];
  nextCursor: string | null;
  requestId: string;
};

/** Minimal ACL-scoped catalog row for the file-scope picker. */
export type FileScopeItem = {
  documentId: string;
  versionId: string;
  logicalName: string;
  displayFilename: string;
  viewerKind: ViewerKind | "unsupported";
  classification: string;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STATES = new Set<AnswerState>(["grounded", "honest_null", "failed"]);
const REASONS = new Set<AnswerReason>([
  "no_evidence",
  "denied_or_unavailable",
  "insufficient_confidence",
  "stale_only",
  "grounding_failed",
  "manual_entry",
  "answer_quality_configuration_required",
]);
const KINDS = new Set(["image", "pdf", "docx", "xlsx", "pptx", "video", "audio"]);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function uuid(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value);
}
function text(value: unknown, maximum = 20_000): value is string {
  return typeof value === "string" && value.length <= maximum
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value);
}
function stamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 64
    && !Number.isNaN(Date.parse(value));
}

export function parseAskAnswer(value: unknown): AskAnswer {
  if (!record(value) || !STATES.has(value.state as AnswerState)
      || !text(value.answer) || !Array.isArray(value.citations)
      || value.citations.length > 20 || !uuid(value.conversation_id)
      || !uuid(value.answer_run_id)
      || !(value.gap_id === null || value.gap_id === undefined || uuid(value.gap_id))
      || !(value.answer_mode === null || value.answer_mode === undefined
        || value.answer_mode === "quality_llm" || value.answer_mode === "evidence_only")
      || !(value.reason_code === null || value.reason_code === undefined
        || REASONS.has(value.reason_code as AnswerReason))
      || !(value.confidence_caveat === undefined
        || typeof value.confidence_caveat === "boolean")
      || !text(value.request_id, 128)) {
    throw new Error("invalid_ask_response");
  }
  const state = value.state as AnswerState;
  if (state !== "grounded" && value.citations.length > 0) {
    // A non-grounded answer may not smuggle citations past the grounding gate.
    throw new Error("invalid_ask_response");
  }
  return {
    state,
    answer: value.answer as string,
    entries: state === "grounded"
      ? value.citations.map(item => evidenceFromAskCitation(item, "grounded"))
      : [],
    conversationId: value.conversation_id as string,
    answerRunId: value.answer_run_id as string,
    gapId: uuid(value.gap_id) ? value.gap_id : null,
    answerMode: value.answer_mode === "quality_llm" || value.answer_mode === "evidence_only"
      ? value.answer_mode : null,
    reasonCode: REASONS.has(value.reason_code as AnswerReason)
      ? value.reason_code as AnswerReason : null,
    // Only a grounded answer can carry the caveat — never inferred client-side.
    confidenceCaveat: state === "grounded" && value.confidence_caveat === true,
    requestId: value.request_id as string,
  };
}

export function parseConversation(value: unknown): Conversation {
  if (!record(value) || !uuid(value.conversation_id)
      || !Array.isArray(value.messages) || value.messages.length > 100
      || !text(value.request_id, 128)) {
    throw new Error("invalid_conversation");
  }
  const messages = value.messages.map((item): ConversationMessage => {
    if (!record(item) || !uuid(item.message_id)
        || (item.role !== "user" && item.role !== "assistant")
        || !text(item.content)
        || !(item.answer_state === null || item.answer_state === undefined
          || text(item.answer_state, 40))
        || !Array.isArray(item.citations) || item.citations.length > 20
        || !stamp(item.created_at)) {
      throw new Error("invalid_conversation_message");
    }
    return {
      messageId: item.message_id as string,
      role: item.role,
      content: item.content as string,
      answerState: text(item.answer_state, 40) && item.answer_state
        ? item.answer_state as string : null,
      entries: item.citations.map(citation =>
        evidenceFromAskCitation(citation, "grounded")),
      createdAt: item.created_at as string,
    };
  });
  return {
    conversationId: value.conversation_id as string,
    messages,
    requestId: value.request_id as string,
  };
}

const HEX64 = /^[0-9a-f]{64}$/i;

export function parseConversationList(value: unknown): ConversationListPage {
  if (!record(value) || !Array.isArray(value.items) || value.items.length > 100
      || !text(value.request_id, 128)) {
    throw new Error("invalid_conversation_list");
  }
  const items = value.items.map((item): ConversationSummary => {
    if (!record(item) || !uuid(item.conversation_id)
        || !stamp(item.started_at) || !stamp(item.last_activity_at)
        || !(item.first_question_digest === null
          || item.first_question_digest === undefined
          || HEX64.test(String(item.first_question_digest)))) {
      throw new Error("invalid_conversation_summary");
    }
    return {
      conversationId: item.conversation_id as string,
      startedAt: item.started_at as string,
      lastActivityAt: item.last_activity_at as string,
      firstQuestionDigest: typeof item.first_question_digest === "string"
        && HEX64.test(item.first_question_digest)
        ? item.first_question_digest : null,
    };
  });
  return {
    items,
    nextCursor: text(value.next_cursor, 512) && value.next_cursor
      ? value.next_cursor as string : null,
    requestId: value.request_id as string,
  };
}

/** Content-free research-scope capability (TIP-011 `/research/scope`). */
export function parseResearchScope(value: unknown): boolean {
  if (!record(value) || typeof value.allowed !== "boolean") {
    throw new Error("invalid_research_scope");
  }
  return value.allowed;
}

export function parseFileScopePage(value: unknown): {
  items: FileScopeItem[]; nextCursor: string | null;
} {
  if (!record(value) || !Array.isArray(value.items) || value.items.length > 200) {
    throw new Error("invalid_catalog_page");
  }
  const items = value.items.map((item): FileScopeItem => {
    if (!record(item) || !uuid(item.document_id) || !uuid(item.version_id)
        || !text(item.logical_name, 500) || !text(item.display_filename, 500)
        || !text(item.classification, 100)) {
      throw new Error("invalid_catalog_item");
    }
    return {
      documentId: item.document_id as string,
      versionId: item.version_id as string,
      logicalName: item.logical_name as string,
      displayFilename: item.display_filename as string,
      viewerKind: KINDS.has(item.viewer_kind as string)
        ? item.viewer_kind as ViewerKind : "unsupported",
      classification: item.classification as string,
    };
  });
  return {
    items,
    nextCursor: text(value.next_cursor, 512) && value.next_cursor
      ? value.next_cursor as string : null,
  };
}

/** URL-restorable Ask state: the conversation id only, never content. */
export function parseAskState(params: URLSearchParams): {conversationId: string | null} {
  const conversation = params.get("conversation");
  return {conversationId: uuid(conversation) ? conversation : null};
}

export function askQuery(conversationId: string | null): string {
  if (!conversationId) return "";
  const params = new URLSearchParams({conversation: conversationId});
  return params.toString();
}
