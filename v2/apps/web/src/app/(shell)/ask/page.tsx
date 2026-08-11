"use client";

/**
 * Ask workspace (TIP-011 Task 2, AC-03/04/05) — consumes the frozen TIP-007
 * answer API as-is (D-011-03) through the same-origin `/api/ask` proxy and
 * renders every result through the shared Evidence Rail.
 *
 * - Scope control: company SOT (default) plus an explicit research scope
 *   gated by the content-free `/research/scope` capability (TIP-011 backend,
 *   same policy predicate as the research search — no per-load audited
 *   search probe); a false capability renders the option disabled with the
 *   denied state; research results render exactly as the backend labels
 *   them (zone_label/tier/grounding).
 * - Optional file scope: picker over the ACL-filtered Files catalog proxy;
 *   the ask API scopes retrieval by immutable `filters.version_id`, so the
 *   picked file's exact version is sent — evidence outside the
 *   caller's policy scope never appears either way.
 * - Honest-null is first-class: the recorded gap id (and its state when the
 *   caller may read the gap) with a Knowledge Ops link for curators.
 * - Conversations reopen via the TIP-007 conversation API; the history
 *   panel lists the caller's own conversations from the TIP-011 list
 *   endpoint (id + timestamps + stored first-question digest only); the id
 *   is URL-restorable and nothing touches localStorage/sessionStorage.
 */

import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import Link from "next/link";
import {useRouter, useSearchParams} from "next/navigation";
import {
  AskAnswer,
  AskProgressEvent,
  AskProgressSource,
  AskProgressStage,
  askQuery,
  Conversation,
  ConversationListPage,
  FileScopeItem,
  parseAskAnswer,
  parseAskProgressEvent,
  parseAskState,
  parseConversation,
  parseConversationList,
  parseFileScopePage,
  parseResearchScope,
} from "../../../ask/contracts";
import {GapDetail, parseGapDetail} from "../../../governance/contracts";
import {formatDateTime, formatNumber} from "../../../i18n/format";
import {MessageKey} from "../../../i18n/messages";
import {useI18n} from "../../../i18n/provider";
import {
  EvidenceEntry,
  parseResearchSearchEvidence,
  ResearchSearchEvidence,
} from "../../../rail/contracts";
import {EvidenceRail, focusRailEntry} from "../../../rail/EvidenceRail";
import {ZoneChip} from "../../../rail/ZoneChip";
import {
  errorText,
  IDLE,
  Load,
  parseTypedError,
  Surface,
} from "../../../shared/surface";
import {PageHeader} from "../../../shell/AppShell";

type Identity = {user_id: string; email: string; display_name: string; roles: string[]};

export type AnswerClaim = {text: string; citations: string[]};
export type AnswerBlock =
  | {kind: "paragraph"; text: string}
  | {kind: "heading"; level: number; text: string}
  | {kind: "list"; ordered: boolean; items: string[]}
  | {kind: "quote"; text: string}
  | {kind: "code"; text: string};

const ASK_PIPELINE: ReadonlyArray<{
  stage: AskProgressStage;
  label: MessageKey;
}> = [
  {stage: "understanding", label: "ask.inspector.stage.understanding"},
  {stage: "retrieving", label: "ask.inspector.stage.retrieving"},
  {stage: "verifying", label: "ask.inspector.stage.verifying"},
  {stage: "synthesizing", label: "ask.inspector.stage.synthesizing"},
  {stage: "grounding", label: "ask.inspector.stage.grounding"},
];

type AskProgressView = {
  events: Partial<Record<AskProgressStage, AskProgressEvent>>;
  elapsedMs: number;
};

const EMPTY_PROGRESS: AskProgressView = {events: {}, elapsedMs: 0};

class AskStreamFailure extends Error {
  constructor(readonly payload: unknown) {
    super("ask_stream_error");
  }
}

function parseSseFrame(frame: string): {event: string; data: unknown} | null {
  let event = "message";
  const data: string[] = [];
  for (const line of frame.replace(/\r/g, "").split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (data.length === 0) return null;
  return {event, data: JSON.parse(data.join("\n")) as unknown};
}

/** Consume POST-SSE while retaining JSON compatibility for tests and clients. */
export async function readAskPayload(
  response: Response,
  onProgress: (event: AskProgressEvent) => void,
  onHeartbeat: (elapsedMs: number) => void,
): Promise<unknown> {
  if (!response.headers.get("content-type")?.includes("text/event-stream")) {
    return response.json().catch(() => null);
  }
  if (!response.body) throw new Error("ask_stream_missing_body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: unknown;

  const consume = (frame: string) => {
    const parsed = parseSseFrame(frame);
    if (!parsed) return;
    if (parsed.event === "progress") {
      onProgress(parseAskProgressEvent(parsed.data));
      return;
    }
    if (parsed.event === "heartbeat") {
      const value = parsed.data as {elapsed_ms?: unknown};
      if (Number.isSafeInteger(value?.elapsed_ms) && Number(value.elapsed_ms) >= 0) {
        onHeartbeat(Number(value.elapsed_ms));
      }
      return;
    }
    if (parsed.event === "result") {
      result = (parsed.data as {response?: unknown})?.response;
      return;
    }
    if (parsed.event === "error") throw new AskStreamFailure(parsed.data);
  };

  while (true) {
    const {done, value} = await reader.read();
    buffer += decoder.decode(value, {stream: !done});
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      consume(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
  if (buffer.trim()) consume(buffer);
  if (result === undefined) throw new Error("ask_stream_missing_result");
  return result;
}

function activeProgressEvent(progress: AskProgressView): AskProgressEvent | null {
  for (const item of [...ASK_PIPELINE].reverse()) {
    const event = progress.events[item.stage];
    if (event?.status === "started") return event;
  }
  return null;
}

function AskProgress({progress}: {progress: AskProgressView}) {
  const {t, locale} = useI18n();
  const active = activeProgressEvent(progress);
  const item = ASK_PIPELINE.find(row => row.stage === active?.stage);
  const message = item ? t(item.label) : t("ask.inspector.waiting");
  return <div className="ask-progress" aria-label={message}>
    <span className="ask-progress-marker" aria-hidden="true"/>
    <span className="ask-progress-message" role="status" aria-live="polite"
      aria-atomic="true">{message}</span>
    <span className="ask-progress-time" aria-hidden="true">
      {formatNumber(Math.floor(progress.elapsedMs / 1000), locale)} {t("ask.progress.seconds")}
    </span>
  </div>;
}

function latestProgressSources(progress: AskProgressView): AskProgressSource[] {
  for (const item of [...ASK_PIPELINE].reverse()) {
    const sources = progress.events[item.stage]?.sources ?? [];
    if (sources.length > 0) return sources;
  }
  return [];
}

type InspectorTab = "process" | "sources" | "details";

function ProcessingInspector({
  progress, asking, entries, onCitation, details, scopeLabel, answerState,
  conversationLabel, open, onClose,
}: {
  progress: AskProgressView;
  asking: boolean;
  entries: EvidenceEntry[];
  onCitation: (key: string) => void;
  details: React.ReactNode;
  scopeLabel: string;
  answerState: string;
  conversationLabel: string;
  open: boolean;
  onClose: () => void;
}) {
  const {t, locale} = useI18n();
  const [tab, setTab] = useState<InspectorTab>("process");
  const candidates = latestProgressSources(progress);
  const usedByRecord = new Map(entries.map(entry => [entry.recordKey, entry]));
  const sourceRows = candidates.length > 0
    ? candidates
    : entries.map(entry => ({
        marker: entry.marker ?? entry.key,
        recordKey: entry.recordKey,
        sourceLabel: entry.sourceLabel,
        verificationState: entry.verificationState ?? "—",
        freshnessState: entry.freshnessState ?? "—",
      }));
  const usedCount = sourceRows.filter(source => usedByRecord.has(source.recordKey)).length;

  const tabLabel = (value: InspectorTab) => t(`ask.inspector.tab.${value}` as MessageKey);

  return <aside id="ask-related-panel"
    className={`processing-inspector ${open ? "open" : ""}`}
    aria-label={t("ask.inspector.title")}>
    <header className="processing-inspector-head">
      <div>
        <p className="eyebrow">{t("ask.inspector.eyebrow")}</p>
        <h2>{t("ask.inspector.related")}</h2>
      </div>
      <code>{formatNumber(Math.floor(progress.elapsedMs / 1000), locale)}s</code>
      <button type="button" className="processing-inspector-close"
        aria-label={t("ask.inspector.close")} onClick={onClose}>×</button>
    </header>
    <div className="processing-tabs" role="tablist"
      aria-label={t("ask.inspector.tabs")}>
      {(["process", "sources", "details"] as const).map(value => <button
        key={value} type="button" role="tab" aria-selected={tab === value}
        aria-controls={`ask-inspector-${value}`} id={`ask-inspector-tab-${value}`}
        onClick={() => setTab(value)}>
        {tabLabel(value)}
        {value === "sources" && sourceRows.length > 0
          && <span>{formatNumber(sourceRows.length, locale)}</span>}
      </button>)}
    </div>
    {tab === "process" && <section className="processing-tab-panel" role="tabpanel"
      id="ask-inspector-process" aria-labelledby="ask-inspector-tab-process">
      <ol className="processing-ledger">
        {ASK_PIPELINE.map(item => {
          const event = progress.events[item.stage];
          const state = event?.status === "completed"
            ? "done" : event?.status === "started" && asking ? "active"
              : event?.status === "started" ? "stopped" : "pending";
          return <li key={item.stage} data-state={state}>
            <span className="processing-node" aria-hidden="true"/>
            <div>
              <strong>{t(item.label)}</strong>
              {event?.detail && <small>{event.detail}</small>}
            </div>
            <span className="processing-state">{t(
              state === "done" ? "ask.inspector.done"
                : state === "active" ? "ask.inspector.running"
                  : state === "stopped" ? "ask.inspector.stopped"
                    : "ask.inspector.pending",
            )}</span>
          </li>;
        })}
      </ol>
    </section>}
    {tab === "sources" && <section className="source-ledger processing-tab-panel"
      role="tabpanel" id="ask-inspector-sources"
      aria-labelledby="ask-inspector-tab-sources"
      aria-label={t("ask.inspector.sources")}>
        <header>
          <h3>{t("ask.inspector.sources")}</h3>
          <span>{sourceRows.length > 0
            ? `${formatNumber(sourceRows.length, locale)} · ${formatNumber(usedCount, locale)}`
            : "—"}</span>
        </header>
        {sourceRows.length === 0
          ? <p className="source-ledger-empty">{t(
              asking ? "ask.inspector.sourcesWaiting" : "ask.inspector.sourcesEmpty",
            )}</p>
          : <ol>{sourceRows.map((source, index) => {
              const used = usedByRecord.get(source.recordKey);
              const content = <>
                <span className="source-marker">[{source.marker}]</span>
                <span className="source-copy">
                  <strong>{source.sourceLabel}</strong>
                  <code>{source.recordKey}</code>
                </span>
                <span className="source-use">{t(
                  used ? "ask.inspector.sourceUsed" : "ask.inspector.sourceChecked",
                )}</span>
              </>;
              return <li key={`${source.recordKey}-${index}`}>
                {used
                  ? <button type="button" onClick={() => onCitation(used.key)}>{content}</button>
                  : <div>{content}</div>}
                <small>{source.verificationState} · {source.freshnessState}</small>
              </li>;
            })}</ol>}
      </section>}
    {tab === "details" && <section className="processing-details processing-tab-panel"
      role="tabpanel" id="ask-inspector-details"
      aria-labelledby="ask-inspector-tab-details">
      <dl>
        <div><dt>{t("ask.inspector.detail.scope")}</dt><dd>{scopeLabel}</dd></div>
        <div><dt>{t("ask.inspector.detail.state")}</dt><dd>{answerState}</dd></div>
        <div><dt>{t("ask.inspector.detail.conversation")}</dt>
          <dd><code>{conversationLabel}</code></dd></div>
      </dl>
      {details}
    </section>}
    <p className="processing-disclosure">{t("ask.inspector.disclosure")}</p>
  </aside>;
}

function normalizeClaimCopy(value: string): string {
  return value
    .replace(/[\t\f\v ]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * The answer contract is plain text with postfixed `[C…]` markers. Treat a
 * marker as a real claim boundary instead of painting one unbroken paragraph.
 * Consecutive markers remain attached to the same claim and are de-duplicated.
 */
export function parseAnswerClaims(text: string): AnswerClaim[] {
  const claims: AnswerClaim[] = [];
  const marker = /\[(C\d{1,3})\]/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = marker.exec(text)) !== null) {
    const copy = normalizeClaimCopy(text.slice(cursor, match.index));
    const citation = match[1];
    if (copy) {
      claims.push({text: copy, citations: [citation]});
    } else if (claims.length > 0) {
      const previous = claims[claims.length - 1];
      if (!previous.citations.includes(citation)) previous.citations.push(citation);
    }
    cursor = marker.lastIndex;
  }

  const tail = normalizeClaimCopy(text.slice(cursor));
  if (tail) claims.push({text: tail, citations: []});
  if (claims.length > 0) return claims;
  const fallback = normalizeClaimCopy(text);
  return fallback ? [{text: fallback, citations: []}] : [];
}

/**
 * Deliberately small, deterministic Markdown block grammar for LLM copy.
 * React still owns escaping; no HTML from an answer is ever interpreted.
 */
export function parseAnswerBlocks(text: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];
  let paragraph: string[] = [];
  let list: {ordered: boolean; items: string[]} | null = null;
  let code: string[] | null = null;

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({kind: "paragraph", text: paragraph.join(" ")});
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      blocks.push({kind: "list", ordered: list.ordered, items: list.items});
      list = null;
    }
  };

  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (line.startsWith("```")) {
      flushParagraph();
      flushList();
      if (code) {
        blocks.push({kind: "code", text: code.join("\n")});
        code = null;
      } else {
        code = [];
      }
      continue;
    }
    if (code) {
      code.push(rawLine);
      continue;
    }
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({kind: "heading", level: heading[1].length, text: heading[2]});
      continue;
    }
    const unordered = /^[-*+]\s+(.+)$/.exec(line);
    const ordered = /^\d+[.)]\s+(.+)$/.exec(line);
    if (unordered || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      const item = (ordered ?? unordered)?.[1] ?? "";
      if (!list || list.ordered !== isOrdered) {
        flushList();
        list = {ordered: isOrdered, items: []};
      }
      list.items.push(item);
      continue;
    }
    const quote = /^>\s?(.+)$/.exec(line);
    if (quote) {
      flushParagraph();
      flushList();
      blocks.push({kind: "quote", text: quote[1]});
      continue;
    }
    flushList();
    paragraph.push(line);
  }

  if (code) blocks.push({kind: "code", text: code.join("\n")});
  flushParagraph();
  flushList();
  return blocks;
}

const INLINE_MARKDOWN = /(\*\*([^*\n]+)\*\*|__([^_\n]+)__|`([^`\n]+)`|\*([^*\n]+)\*|_([^_\n]+)_|\[([^\]\n]+)\]\(https?:\/\/[^\s)]+\))/g;

function plainMarkdown(value: string) {
  // A malformed model delimiter must never leak into the polished surface.
  return value.replace(/\*\*/g, "").replace(/__/g, "");
}

/** Safe inline emphasis: React escapes all text and URLs stay non-activatable. */
function MarkdownInline({text}: {text: string}) {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  const inlineMarkdown = new RegExp(INLINE_MARKDOWN.source, "g");
  while ((match = inlineMarkdown.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(plainMarkdown(text.slice(cursor, match.index)));
    if (match[2] || match[3]) {
      nodes.push(<strong key={`strong-${match.index}`}>
        {plainMarkdown(match[2] ?? match[3])}</strong>);
    } else if (match[4]) {
      nodes.push(<code key={`code-${match.index}`}>{match[4]}</code>);
    } else if (match[5] || match[6]) {
      nodes.push(<em key={`em-${match.index}`}>
        {plainMarkdown(match[5] ?? match[6])}</em>);
    } else if (match[7]) {
      // Grounded source navigation belongs to [C…] markers, not model links.
      nodes.push(<span className="answer-link-label" key={`link-${match.index}`}>
        {match[7]}</span>);
    }
    cursor = inlineMarkdown.lastIndex;
  }
  if (cursor < text.length) nodes.push(plainMarkdown(text.slice(cursor)));
  return <>{nodes}</>;
}

function ClaimCitations({citations, onCitation}: {
  citations: string[]; onCitation: (marker: string) => void;
}) {
  const {t} = useI18n();
  if (citations.length === 0) return null;
  return <span className="answer-citations">
    {citations.map(citation => <button key={citation} type="button"
      className="citation-marker"
      aria-label={`${t("ask.citation.aria")} ${citation}`}
      onClick={() => onCitation(citation)}>[{citation}]</button>)}
  </span>;
}

function AnswerBlockView({block, trailing}: {
  block: AnswerBlock; trailing?: React.ReactNode;
}) {
  if (block.kind === "heading") {
    return block.level <= 2
      ? <h3><MarkdownInline text={block.text}/>{trailing}</h3>
      : <h4><MarkdownInline text={block.text}/>{trailing}</h4>;
  }
  if (block.kind === "list") {
    const List = block.ordered ? "ol" : "ul";
    return <List>{block.items.map((item, index) => <li key={`${index}-${item}`}>
      <MarkdownInline text={item}/>{index === block.items.length - 1 && trailing}
    </li>)}</List>;
  }
  if (block.kind === "quote") {
    return <blockquote><MarkdownInline text={block.text}/>{trailing}</blockquote>;
  }
  if (block.kind === "code") {
    return <div className="answer-code-block"><pre><code>{block.text}</code></pre>
      {trailing}</div>;
  }
  return <p><MarkdownInline text={block.text}/>{trailing}</p>;
}

/** A safe Markdown claim ledger with citation markers wired to the rail. */
export function AnswerText({text, onCitation}: {
  text: string; onCitation: (marker: string) => void;
}) {
  const claims = useMemo(() => parseAnswerClaims(text), [text]);
  return <div className="answer-content">
    {claims.map((claim, index) => {
      const blocks = parseAnswerBlocks(claim.text);
      return <div className="answer-claim" data-lead={index === 0 ? "true" : undefined}
        key={`${index}-${claim.text.slice(0, 24)}`}>
        <div className="answer-text answer-markdown">
          {blocks.map((block, blockIndex) => <AnswerBlockView
            key={`${blockIndex}-${block.kind}`}
            block={block}
            trailing={blockIndex === blocks.length - 1
              ? <ClaimCitations citations={claim.citations} onCitation={onCitation}/>
              : undefined}/>) }
        </div>
      </div>;
    })}
  </div>;
}

export default function AskPage() {
  const {t, locale} = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialPrefill = searchParams.get("q")?.trim() ?? "";
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [question, setQuestion] = useState(initialPrefill);
  const [includeResearch, setIncludeResearch] = useState(false);
  const [researchAccess, setResearchAccess] = useState<Load<boolean>>(IDLE);
  const [fileScope, setFileScope] = useState<FileScopeItem | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [fileQuery, setFileQuery] = useState("");
  const [catalog, setCatalog] = useState<Load<FileScopeItem[]>>(IDLE);
  const [answer, setAnswer] = useState<Load<AskAnswer>>(IDLE);
  const [research, setResearch] = useState<Load<ResearchSearchEvidence>>(IDLE);
  const [gap, setGap] = useState<Load<GapDetail>>(IDLE);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversation, setConversation] = useState<Load<Conversation>>(IDLE);
  const [history, setHistory] = useState<Load<ConversationListPage>>(IDLE);
  const [activeCitation, setActiveCitation] = useState<string | null>(null);
  const [railOpen, setRailOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const [askProgress, setAskProgress] = useState<AskProgressView>(EMPTY_PROGRESS);
  const [lastQuestion, setLastQuestion] = useState("");
  const [relatedOpen, setRelatedOpen] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);
  const lastPrefill = useRef(initialPrefill);
  const composingRef = useRef(false);
  const submittingRef = useRef(false);
  const draftRevisionRef = useRef(0);
  const askSequenceRef = useRef(0);
  const askAbortRef = useRef<AbortController | null>(null);
  const ignoredConversationRef = useRef<string | null>(null);
  const requestedConversation = parseAskState(searchParams).conversationId;

  // PRD §11 composer: auto-expand the question textarea between 64 and 180px
  // (DOM-only; never a layout-animating transition, reduced-motion safe).
  const autoGrow = useCallback(() => {
    const el = questionRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 64), 180)}px`;
  }, []);

  const changeQuestion = useCallback((value: string) => {
    draftRevisionRef.current += 1;
    setQuestion(value);
    autoGrow();
  }, [autoGrow]);

  /**
   * Clear both React state and the live control in the same interaction frame.
   * The direct DOM clear prevents an IME composition-end event from leaving a
   * one-frame stale draft before React commits the controlled value.
   */
  const clearComposer = useCallback(() => {
    draftRevisionRef.current += 1;
    const clearedRevision = draftRevisionRef.current;
    composingRef.current = false;
    setQuestion("");
    if (questionRef.current) questionRef.current.value = "";
    requestAnimationFrame(autoGrow);
    return clearedRevision;
  }, [autoGrow]);

  const restoreComposer = useCallback((value: string, clearedRevision: number) => {
    // A user may already be writing the next message while the request is in
    // flight. Never replace that newer draft with the failed submission.
    if (draftRevisionRef.current !== clearedRevision) return;
    draftRevisionRef.current += 1;
    setQuestion(value);
    requestAnimationFrame(() => {
      autoGrow();
      questionRef.current?.focus();
    });
  }, [autoGrow]);

  const cancelActiveAsk = useCallback(() => {
    askSequenceRef.current += 1;
    askAbortRef.current?.abort();
    askAbortRef.current = null;
    submittingRef.current = false;
    setAsking(false);
  }, []);

  const loseAccess = useCallback(() => {
    cancelActiveAsk();
    setIdentity(null);
    setResearchAccess(IDLE); setCatalog(IDLE); setAnswer(IDLE);
    setResearch(IDLE); setGap(IDLE); setConversation(IDLE);
    setFileScope(null); setPickerOpen(false); setHistory(IDLE);
    setConversationId(null); setActiveCitation(null);
    setAskProgress(EMPTY_PROGRESS);
    setLastQuestion(""); setRelatedOpen(false);
  }, [cancelActiveAsk]);

  useEffect(() => () => {
    askSequenceRef.current += 1;
    askAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    fetch("/api/auth/me", {cache: "no-store"})
      .then(async response => setIdentity(
        response.ok ? await response.json() as Identity : null,
      ))
      .catch(() => setIdentity(null)).finally(() => setAuthReady(true));
  }, []);

  // Next.js client navigation can change only the query string while keeping
  // this page mounted. Deriving state from useSearchParams fixes recent-link
  // navigation without a reload; `q` is a deliberate prefill, never an
  // automatic submission.
  useEffect(() => {
    const prefill = searchParams.get("q")?.trim() ?? "";
    if (!prefill) {
      lastPrefill.current = "";
      return;
    }
    if (prefill === lastPrefill.current) return;
    const timer = setTimeout(() => {
      lastPrefill.current = prefill;
      changeQuestion(prefill);
      requestAnimationFrame(() => { autoGrow(); questionRef.current?.focus(); });
    }, 0);
    return () => clearTimeout(timer);
  }, [searchParams, autoGrow, changeQuestion]);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setRailOpen(false); setRelatedOpen(false); setPickerOpen(false);
      }
    };
    addEventListener("keydown", close);
    return () => removeEventListener("keydown", close);
  }, []);

  // Research-scope capability (TIP-011): a content-free boolean from the
  // same policy predicate the research search uses — no audited probe.
  useEffect(() => {
    if (!identity) return;
    let active = true;
    const timer = setTimeout(() => {
      setResearchAccess({state: "loading"});
      fetch("/api/governance/research/scope", {cache: "no-store"})
        .then(async response => {
          if (!active) return;
          if (response.status === 401) return loseAccess();
          const body: unknown = await response.json().catch(() => null);
          if (response.status === 403) {
            return setResearchAccess({state: "denied", error: parseTypedError(body)});
          }
          if (!response.ok) {
            return setResearchAccess({state: "error", error: parseTypedError(body)});
          }
          setResearchAccess({state: "ready", data: parseResearchScope(body)});
        }).catch(() => {
          if (active) {
            setResearchAccess({state: "error", error: {
              code: "ask_service_unavailable", message: "", requestId: "",
            }});
          }
        });
    }, 0);
    return () => { active = false; clearTimeout(timer); };
  }, [identity, loseAccess]);

  // The caller's own conversation history (TIP-011 list endpoint):
  // metadata only, refreshed after every completed ask.
  const loadHistory = useCallback(() => {
    fetch("/api/ask/conversations?limit=25", {cache: "no-store"})
      .then(async response => {
        if (response.status === 401) return loseAccess();
        const body: unknown = await response.json().catch(() => null);
        if (response.status === 403) {
          return setHistory({state: "denied", error: parseTypedError(body)});
        }
        if (!response.ok) {
          return setHistory({state: "error", error: parseTypedError(body)});
        }
        setHistory({state: "ready", data: parseConversationList(body)});
      })
      .catch(() => setHistory({state: "error", error: {
        code: "contract_violation", message: "", requestId: "",
      }}));
  }, [loseAccess]);

  useEffect(() => {
    if (!identity) return;
    const timer = setTimeout(() => {
      setHistory({state: "loading"});
      loadHistory();
    }, 0);
    return () => clearTimeout(timer);
  }, [identity, loadHistory]);

  // File-scope picker over the ACL-filtered Files catalog proxy.
  useEffect(() => {
    if (!identity || !pickerOpen) return;
    let active = true;
    const params = new URLSearchParams({limit: "25"});
    if (fileQuery.trim()) params.set("query", fileQuery.trim());
    const delay = setTimeout(() => {
      setCatalog({state: "loading"});
      fetch(`/api/files?${params}`, {cache: "no-store"}).then(async response => {
        if (!active) return;
        if (response.status === 401) return loseAccess();
        const body: unknown = await response.json().catch(() => null);
        if (response.status === 403) {
          return setCatalog({state: "denied", error: parseTypedError(body)});
        }
        if (!response.ok) return setCatalog({state: "error", error: parseTypedError(body)});
        setCatalog({state: "ready", data: parseFileScopePage(body).items});
      }).catch(() => {
        if (active) {
          setCatalog({state: "error", error: {
            code: "contract_violation", message: "", requestId: "",
          }});
        }
      });
    }, 150);
    return () => { active = false; clearTimeout(delay); };
  }, [identity, pickerOpen, fileQuery, loseAccess]);

  // Reopen a conversation (URL-restorable id; TIP-007 conversation API).
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      if (!requestedConversation) ignoredConversationRef.current = null;
      if (!identity || !requestedConversation
          || requestedConversation === ignoredConversationRef.current
          || (answer.state === "ready"
            && answer.data.conversationId === requestedConversation)) {
        setConversation(IDLE);
        return;
      }
      setConversation({state: "loading"});
      fetch(`/api/ask/conversations/${requestedConversation}`, {cache: "no-store"})
        .then(async response => {
          if (!active) return;
          if (response.status === 401) return loseAccess();
          const body: unknown = await response.json().catch(() => null);
          if (response.status === 403) {
            return setConversation({state: "denied", error: parseTypedError(body)});
          }
          if (!response.ok) {
            return setConversation({state: "error", error: parseTypedError(body)});
          }
          const parsed = parseConversation(body);
          setConversation({state: "ready", data: parsed});
          setConversationId(parsed.conversationId);
        })
        .catch(() => {
          if (active) {
            setConversation({state: "error", error: {
              code: "contract_violation", message: "", requestId: "",
            }});
          }
        });
    }, 0);
    return () => { active = false; clearTimeout(timer); };
  }, [identity, requestedConversation, answer, loseAccess]);

  // Keep the newest turn in view: whenever a question is submitted, the answer
  // surface changes, or the persisted transcript grows, scroll the sentinel at
  // the bottom of the thread into view (chat-client behaviour).
  useEffect(() => {
    const sentinel = threadEndRef.current;
    if (typeof sentinel?.scrollIntoView === "function") {
      sentinel.scrollIntoView({behavior: "smooth", block: "end"});
    }
  }, [lastQuestion, answer, asking, conversation]);

  // Best-effort gap detail after honest-null (state shown when readable).
  const loadGap = useCallback((gapId: string) => {
    setGap({state: "loading"});
    fetch(`/api/governance/gaps/${gapId}`, {cache: "no-store"})
      .then(async response => {
        if (response.status === 401) return loseAccess();
        const body: unknown = await response.json().catch(() => null);
        if (response.status === 403) {
          return setGap({state: "denied", error: parseTypedError(body)});
        }
        if (!response.ok) return setGap({state: "error", error: parseTypedError(body)});
        setGap({state: "ready", data: parseGapDetail(body)});
      })
      .catch(() => setGap({state: "error", error: {
        code: "contract_violation", message: "", requestId: "",
      }}));
  }, [loseAccess]);

  const submit = useCallback(async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = (questionRef.current?.value ?? question).trim();
    if (!trimmed || submittingRef.current) return;
    submittingRef.current = true;
    const askSequence = ++askSequenceRef.current;
    const controller = new AbortController();
    askAbortRef.current?.abort();
    askAbortRef.current = controller;
    const isCurrentAsk = () => askSequenceRef.current === askSequence
      && !controller.signal.aborted;
    setLastQuestion(trimmed);
    const clearedRevision = clearComposer();
    setAsking(true);
    setAnswer({state: "loading"});
    setAskProgress(EMPTY_PROGRESS);
    setGap(IDLE);
    setConversation(IDLE);
    setActiveCitation(null);
    setResearch(includeResearch ? {state: "loading"} : IDLE);
    if (includeResearch) {
      fetch("/api/governance/research/search", {
        method: "POST", cache: "no-store",
        headers: {"content-type": "application/json"},
        signal: controller.signal,
        body: JSON.stringify({query: trimmed, limit: 10}),
      }).then(async response => {
        if (!isCurrentAsk()) return;
        if (response.status === 401) return loseAccess();
        const body: unknown = await response.json().catch(() => null);
        if (response.status === 403) {
          return setResearch({state: "denied", error: parseTypedError(body)});
        }
        if (!response.ok) return setResearch({state: "error", error: parseTypedError(body)});
        setResearch({state: "ready", data: parseResearchSearchEvidence(body)});
      }).catch(failure => {
        if (!isCurrentAsk() || (failure instanceof DOMException
          && failure.name === "AbortError")) return;
        setResearch({state: "error", error: {
          code: "contract_violation", message: "", requestId: "",
        }});
      });
    }
    try {
      const response = await fetch("/api/ask/ask", {
        method: "POST", cache: "no-store",
        signal: controller.signal,
        headers: {
          "content-type": "application/json",
          accept: "text/event-stream",
        },
        body: JSON.stringify({
          question: trimmed,
          ...(conversationId ? {conversation_id: conversationId} : {}),
          ...(fileScope ? {filters: {version_id: fileScope.versionId}} : {}),
        }),
      });
      if (!isCurrentAsk()) return;
      if (response.status === 401) return loseAccess();
      const body: unknown = response.ok
        ? await readAskPayload(
            response,
            event => {
              if (isCurrentAsk()) setAskProgress(current => ({
                elapsedMs: Math.max(current.elapsedMs, event.elapsedMs),
                events: {...current.events, [event.stage]: event},
              }));
            },
            elapsedMs => {
              if (isCurrentAsk()) setAskProgress(current => ({
                ...current,
                elapsedMs: Math.max(current.elapsedMs, elapsedMs),
              }));
            },
          )
        : await response.json().catch(() => null);
      if (!isCurrentAsk()) return;
      if (response.status === 403) {
        restoreComposer(trimmed, clearedRevision);
        return setAnswer({state: "denied", error: parseTypedError(body)});
      }
      if (!response.ok) {
        restoreComposer(trimmed, clearedRevision);
        return setAnswer({state: "error", error: parseTypedError(body)});
      }
      const parsed = parseAskAnswer(body);
      setAnswer({state: "ready", data: parsed});
      setConversationId(parsed.conversationId);
      // URL-restorable conversation id only — never content, never storage.
      router.replace(`/ask?${askQuery(parsed.conversationId)}`, {scroll: false});
      loadHistory();
      if (parsed.state === "honest_null" && parsed.gapId) loadGap(parsed.gapId);
    } catch (failure) {
      if (!isCurrentAsk() || (failure instanceof DOMException
        && failure.name === "AbortError")) return;
      restoreComposer(trimmed, clearedRevision);
      if (failure instanceof AskStreamFailure) {
        setAnswer({state: "error", error: parseTypedError(failure.payload)});
        return;
      }
      setAnswer({state: "error", error: {
        code: "contract_violation", message: "", requestId: "",
      }});
    } finally {
      if (askSequenceRef.current === askSequence) {
        askAbortRef.current = null;
        submittingRef.current = false;
        setAsking(false);
      }
    }
  }, [
    question, includeResearch, conversationId, fileScope, clearComposer,
    loadGap, loadHistory, loseAccess, restoreComposer, router,
  ]);

  const openCitation = useCallback((key: string) => {
    setActiveCitation(key);
    setRailOpen(true);
    requestAnimationFrame(() => focusRailEntry(key));
  }, []);

  const reopenConversation = useCallback((id: string) => {
    cancelActiveAsk();
    ignoredConversationRef.current = null;
    router.push(`/ask?${askQuery(id)}`, {scroll: false});
    setConversationId(id);
    setAnswer(IDLE); setResearch(IDLE); setGap(IDLE);
    setActiveCitation(null);
    setAskProgress(EMPTY_PROGRESS);
    setLastQuestion(""); setRelatedOpen(false); clearComposer();
  }, [cancelActiveAsk, clearComposer, router]);

  const newConversation = useCallback(() => {
    cancelActiveAsk();
    ignoredConversationRef.current = requestedConversation ?? conversationId;
    router.push("/ask", {scroll: false});
    setConversationId(null);
    setAnswer(IDLE); setResearch(IDLE); setGap(IDLE);
    setConversation(IDLE); setActiveCitation(null); clearComposer();
    setAskProgress(EMPTY_PROGRESS);
    setLastQuestion(""); setRelatedOpen(false);
  }, [cancelActiveAsk, clearComposer, conversationId, requestedConversation, router]);

  const railEntries = useMemo<EvidenceEntry[]>(() => {
    const base = answer.state === "ready"
      ? answer.data.entries
      : conversation.state === "ready"
        ? [...conversation.data.messages].reverse()
            .find(message => message.entries.length > 0)?.entries ?? []
        : [];
    const researchEntries = research.state === "ready" ? research.data.entries : [];
    return [...base, ...researchEntries];
  }, [answer, conversation, research]);

  // PRD §14: with focus inside the Evidence Rail, `[` / `]` step the active
  // citation to the previous / next entry (wraps) and move focus with it.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "[" && event.key !== "]") return;
      const rail = document.getElementById("evidence-rail");
      if (!rail || !rail.contains(document.activeElement) || railEntries.length === 0) return;
      event.preventDefault();
      const keys = railEntries.map(entry => entry.key);
      const step = event.key === "]" ? 1 : -1;
      const current = activeCitation ? keys.indexOf(activeCitation) : -1;
      const base = current === -1 ? (step === 1 ? -1 : 0) : current;
      const nextKey = keys[(base + step + keys.length) % keys.length];
      setActiveCitation(nextKey);
      requestAnimationFrame(() => focusRailEntry(nextKey));
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [railEntries, activeCitation]);

  if (!authReady || !identity) {
    return <>
      <PageHeader eyebrow={t("ask.eyebrow")} title={t("ask.title")}/>
      <section className="placeholder-card">
        {!authReady && <p role="status">{t("shell.sessionChecking")}</p>}
        {authReady && <p className="lede">{t("ask.gate.lede")}</p>}
      </section>
    </>;
  }

  const current = answer.state === "ready" ? answer.data : null;
  const answerSetupRequired = current?.state === "honest_null"
    && current.reasonCode === "answer_quality_configuration_required";

  const historyPanel = <details className="ask-history" aria-label={t("ask.history.title")}>
    <summary>{t("ask.history.title")}</summary>
    <Surface load={history} empty={t("ask.history.empty")}>{page =>
      page.items.length === 0
        ? <p className="surface-empty">{t("ask.history.empty")}</p>
        : <ol>{page.items.map(item => <li key={item.conversationId}>
            <span className="ask-history-question">
              {t("shell.recent.conversation")} · {formatDateTime(item.startedAt, locale, {
                day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
              })}
            </span>
            <small>{formatDateTime(item.lastActivityAt, locale)}</small>
            <button type="button" onClick={() => reopenConversation(item.conversationId)}>
              {t("ask.history.reopen")}
            </button>
          </li>)}</ol>}
    </Surface>
  </details>;
  const scopeLabel = fileScope
    ? `${t("ask.chip.file")} · ${fileScope.displayFilename}`
    : includeResearch ? t("ask.chip.research") : t("ask.chip.sot");
  const answerState = current?.state ?? answer.state;
  const conversationLabel = conversationId ?? requestedConversation ?? "—";

  return <div className="ask-workspace">
    <PageHeader eyebrow={t("ask.eyebrow")} title={t("ask.title")}
      actions={<div className="ask-chatbar-actions">
        <button className="ask-rail-toggle" type="button"
          disabled={railEntries.length === 0}
          onClick={() => setRailOpen(true)}>{t("ask.evidenceButton")}</button>
      </div>}/>
    <div className="ask-layout">
      {/* Distinct landmark name — the grounded-answer region below carries
          "Câu trả lời"; duplicate names were an axe landmark-unique finding
          (TIP-011 Builder D, AC-10). */}
      <section className="ask-surface" aria-label={t("ask.surfaceAria")}>
        <form className="ask-form" ref={formRef} onSubmit={event => void submit(event)}
          aria-busy={asking}>
          <label className="ask-question"><span className="sr-only">
            {t("ask.question.label")}</span>
            <textarea ref={questionRef} value={question} rows={1}
              placeholder={t("ask.question.placeholder")}
              onChange={event => changeQuestion(event.currentTarget.value)}
              onCompositionStart={() => { composingRef.current = true; }}
              onCompositionEnd={event => {
                composingRef.current = false;
                changeQuestion(event.currentTarget.value);
              }}
              onKeyDown={event => {
                // Enter submits; Shift+Enter inserts a newline (PRD §11).
                if (event.key === "Enter" && !event.shiftKey) {
                  const native = event.nativeEvent;
                  if (composingRef.current || native.isComposing
                    || native.keyCode === 229) return;
                  event.preventDefault();
                  formRef.current?.requestSubmit();
                }
              }}/>
          </label>
          <div className="ask-composer-context">
          <div className="ask-chips">
            <span className="ask-chip">
              <span className="ask-chip-key">{t("ask.chip.scope")}</span>
              {includeResearch ? t("ask.chip.research") : t("ask.chip.sot")}
            </span>
            {fileScope && <span className="ask-chip ask-chip-file">
              <span className="ask-chip-key">{t("ask.chip.file")}</span>
              <code>{fileScope.displayFilename}</code>
              <button type="button" aria-label={t("ask.chip.remove")}
                onClick={() => setFileScope(null)}>×</button>
            </span>}
          </div>
          <details className="ask-advanced">
            <summary>{t("ask.advanced")}</summary>
            <div className="ask-advanced-body">
          <fieldset className="ask-scope">
            <legend>{t("ask.scope.legend")}</legend>
            <label>
              <input type="radio" name="ask-scope" checked={!includeResearch}
                onChange={() => setIncludeResearch(false)}/>
              {t("ask.scope.sot")}
            </label>
            <label>
              <input type="radio" name="ask-scope" checked={includeResearch}
                disabled={researchAccess.state !== "ready" || !researchAccess.data}
                onChange={() => setIncludeResearch(true)}/>
              {t("ask.scope.research")}
            </label>
            {researchAccess.state === "loading"
              && <p role="status" className="form-note">{t("ask.scope.researchChecking")}</p>}
            {researchAccess.state === "ready" && !researchAccess.data
              && <p role="note" className="surface-denied">
                {t("ask.scope.researchDenied")}</p>}
            {researchAccess.state === "denied" && <p role="note" className="surface-denied">
              {t("ask.scope.researchDenied")} · {errorText(researchAccess.error)}</p>}
            {researchAccess.state === "error" && <p role="note" className="surface-error">
              {t("ask.scope.researchUnavailable")} · {errorText(researchAccess.error)}</p>}
          </fieldset>
          <fieldset className="ask-file-scope">
            <legend>{t("ask.file.legend")}</legend>
            {fileScope
              ? <p className="ask-file-current">
                  <code>{fileScope.displayFilename}</code>
                  <span> · {fileScope.classification}</span>
                  <button type="button" onClick={() => setFileScope(null)}>
                    {t("ask.file.clear")}
                  </button>
                </p>
              : <p className="ask-file-current">{t("ask.file.none")}</p>}
            <button type="button" aria-expanded={pickerOpen}
              onClick={() => setPickerOpen(open => !open)}>
              {pickerOpen ? t("ask.file.close") : t("ask.file.pick")}
            </button>
            {pickerOpen && <div className="ask-file-picker">
              <label>{t("ask.file.pick")}
                <input value={fileQuery}
                  onChange={event => setFileQuery(event.target.value)}/>
              </label>
              <Surface load={catalog} empty={t("ask.file.empty")}>{items =>
                items.length === 0
                  ? <p className="surface-empty">{t("ask.file.empty")}</p>
                  : <ul className="ask-file-list">{items.map(item =>
                      <li key={item.versionId}>
                        <button type="button" onClick={() => {
                          setFileScope(item);
                          setPickerOpen(false);
                        }}>
                          <span className="file-kind">{item.viewerKind}</span>
                          <strong>{item.displayFilename}</strong>
                          <small>{item.classification}</small>
                        </button>
                      </li>)}
                    </ul>}
              </Surface>
              <p className="form-note">{t("ask.file.note")}</p>
            </div>}
          </fieldset>
            </div>
          </details>
          </div>
          <div className="action-row">
            {(conversationId || conversation.state !== "idle") && <button type="button"
              onClick={newConversation}>{t("ask.history.new")}</button>}
            <span className="ask-composer-hint">{t("ask.composer.hint")}</span>
            <button type="submit" className="primary ask-send"
              disabled={!question.trim() || asking}>
              <span className="sr-only">{t("ask.submit")}</span>
              <span aria-hidden="true">↑</span>
            </button>
          </div>
        </form>

        <div className="ask-thread"><div className="ask-thread-inner">
        {!lastQuestion && answer.state === "idle" && conversation.state === "idle"
          && research.state === "idle" && <section className="ask-empty-state">
            <span aria-hidden="true">RtR</span>
            <h2>{t("ask.thread.emptyTitle")}</h2>
            <p>{t("ask.thread.emptyBody")}</p>
          </section>}
        {/* Persisted transcript renders FIRST (oldest→newest, top→bottom) so the
            live turn below is the newest content at the bottom — matching the
            reading order of ChatGPT/Claude rather than newest-on-top. */}
        {conversation.state === "loading"
          && <p role="status" className="surface-loading">{t("surface.loading")}</p>}
        {conversation.state === "denied" && <div role="alert" className="surface-denied">
          {t("surface.denied")} · {errorText(conversation.error)}</div>}
        {conversation.state === "error" && <div role="alert" className="surface-error">
          {t("ask.blocked")} · {errorText(conversation.error)}</div>}
        {conversation.state === "ready" && <section className="ask-conversation"
          aria-label={t("ask.conversation.title")}>
          <h2>{t("ask.conversation.title")}</h2>
          <p className="form-note"><code>{conversation.data.conversationId}</code></p>
          <ol className="conversation-messages">
            {conversation.data.messages.map(message => <li key={message.messageId}
              data-role={message.role}>
              <p className="message-meta">
                <strong>{message.role === "user"
                  ? t("ask.conversation.you") : t("ask.conversation.assistant")}</strong>
                {message.answerState && <code>{message.answerState}</code>}
                <small>{formatDateTime(message.createdAt, locale)}</small>
              </p>
              <AnswerText text={message.content} onCitation={openCitation}/>
            </li>)}
          </ol>
        </section>}
        {/* Live user bubble: shown as soon as the user submits (asking) or any
            answer surface is active — including follow-ups inside an existing
            conversation (previously hidden by `conversation.state !== "ready"`). */}
        {lastQuestion && (asking || answer.state !== "idle") && <article
          className="ask-turn ask-turn-user" aria-label={t("ask.conversation.you")}>
          <p>{lastQuestion}</p>
        </article>}
        {answer.state === "loading" && <div className="ask-turn ask-turn-assistant">
          <AskProgress progress={askProgress}/>
        </div>}
        {answer.state === "denied" && <div role="alert" className="surface-denied">
          {t("surface.denied")} · {errorText(answer.error)}</div>}
        {answer.state === "error" && <div role="alert" className="surface-error">
          {t("ask.blocked")} · {errorText(answer.error)}</div>}

        {current && current.state === "grounded" && <section className="ask-answer"
          aria-label={t("ask.answer.title")}>
          <header className="answer-header">
            <h2>{t("ask.answer.title")}</h2>
            <p className="grounding-note">{t(
              current.answerMode === "evidence_only"
                ? "ask.answer.evidenceOnly"
                : "ask.answer.grounded",
            )}</p>
          </header>
          <AnswerText text={current.answer} onCitation={openCitation}/>
          {current.coverageState === "partial" && <p className="coverage-caveat"
            role="note">{t("ask.coverage.partial")}</p>}
          {/* TIP-013B AC-4: shown ONLY when the answer is grounded on a softly
              verified fact — a small, legible double-check caveat, reachable
              as a note by keyboard/screenreader. */}
          {current.confidenceCaveat && <p className="confidence-caveat" role="note">
            {t("ask.confidenceCaveat")}</p>}
        </section>}

        {current && current.state === "honest_null" && <section className="honest-null"
          aria-label={t(answerSetupRequired ? "ask.setup.title" : "ask.null.title")}>
          <h2>{t(answerSetupRequired ? "ask.setup.title" : "ask.null.title")}</h2>
          <p className="honest-null-answer">{current.answer}</p>
          <p className="form-note">
            {t(answerSetupRequired ? "ask.setup.body" : "ask.null.body")}
          </p>
          {current.gapId && <dl className="detail-facts">
            <div><dt>{t("ask.null.gap")}</dt>
              <dd><code>{current.gapId}</code></dd></div>
            <div><dt>{t("ask.null.gapState")}</dt><dd>
              {gap.state === "ready"
                ? <code>{gap.data.gap.lifecycle}</code>
                : gap.state === "loading"
                  ? <span role="status">{t("surface.loading")}</span>
                  : <span>{t("ask.null.gapStateHidden")}</span>}
            </dd></div>
          </dl>}
          {current.gapId && <Link className="gap-link"
            href={`/knowledge-ops?view=gaps&gap=${current.gapId}`}>
            {t("ask.null.link")}
          </Link>}
        </section>}

        {current && current.state === "failed" && <div role="alert" className="surface-error">
          {t("ask.answer.failed")} · {current.answer}</div>}

        {research.state === "loading"
          && <p role="status" className="surface-loading">{t("surface.loading")}</p>}
        {research.state === "denied" && <div role="alert" className="surface-denied">
          {t("ask.scope.researchDenied")} · {errorText(research.error)}</div>}
        {research.state === "error" && <div role="alert" className="surface-error">
          {t("ask.blocked")} · {errorText(research.error)}</div>}
        {research.state === "ready" && <section className="ask-research"
          aria-label={t("ask.research.title")}>
          <header className="row-head">
            <ZoneChip zone={research.data.zone}/>
            <h2>{t("ask.research.title")}</h2>
          </header>
          <p className="form-note">{t("ask.research.note")}</p>
          {research.data.entries.length === 0
            ? <p className="surface-empty">{t("ask.research.empty")}</p>
            : <ol className="research-hits">{research.data.entries.map(entry =>
                <li key={entry.key}>
                  <button type="button" className="research-hit"
                    onClick={() => openCitation(entry.key)}>
                    <span className="row-head">
                      <ZoneChip zone={entry.zone}/>
                      <code>Tier {entry.tier}</code>
                      <code>{entry.corroborationState}</code>
                    </span>
                    <strong>{entry.recordKey}</strong>
                    <span className="hit-snippet">{entry.snippet}</span>
                  </button>
                </li>)}
              </ol>}
        </section>}

        {/* Auto-scroll sentinel: the thread scrolls this into view whenever a new
            question is asked or an answer arrives, keeping the newest turn visible
            like a chat client. */}
        <div ref={threadEndRef} aria-hidden="true"/>
        </div></div>
      </section>

      <ProcessingInspector progress={askProgress} asking={asking}
        entries={railEntries} onCitation={openCitation} details={historyPanel}
        scopeLabel={scopeLabel} answerState={answerState}
        conversationLabel={conversationLabel} open={relatedOpen}
        onClose={() => setRelatedOpen(false)}/>

      <button className="ask-related-toggle" type="button"
        aria-expanded={relatedOpen} aria-controls="ask-related-panel"
        onClick={() => setRelatedOpen(open => !open)}>{t("ask.relatedButton")}</button>

      <EvidenceRail entries={railEntries} activeKey={activeCitation}
        open={railOpen} onClose={() => setRailOpen(false)}/>
    </div>
    {relatedOpen && <button className="ask-related-scrim" type="button"
      aria-label={t("ask.inspector.close")} onClick={() => setRelatedOpen(false)}/>}
    {railOpen && <button className="ask-scrim" type="button"
      aria-label={t("rail.close")} onClick={() => setRailOpen(false)}/>}
  </div>;
}
