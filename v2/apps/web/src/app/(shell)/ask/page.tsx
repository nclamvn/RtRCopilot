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
 *   the frozen ask API scopes retrieval by `filters.source_key`, so the
 *   picked file's logical name is sent as that key — evidence outside the
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
import {
  AskAnswer,
  askQuery,
  Conversation,
  ConversationListPage,
  FileScopeItem,
  parseAskAnswer,
  parseAskState,
  parseConversation,
  parseConversationList,
  parseFileScopePage,
  parseResearchScope,
} from "../../../ask/contracts";
import {GapDetail, parseGapDetail} from "../../../governance/contracts";
import {formatDateTime} from "../../../i18n/format";
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

const MARKER_SPLIT = /(\[C\d{1,3}\])/g;
const MARKER_EXACT = /^\[(C\d{1,3})\]$/;

/** Answer text with activatable citation markers wired to the rail. */
function AnswerText({text, onCitation}: {
  text: string; onCitation: (marker: string) => void;
}) {
  const {t} = useI18n();
  const parts = text.split(MARKER_SPLIT);
  return <p className="answer-text">
    {parts.map((part, index) => {
      const match = MARKER_EXACT.exec(part);
      if (!match) return <React.Fragment key={index}>{part}</React.Fragment>;
      const marker = match[1];
      return <button key={index} type="button" className="citation-marker"
        aria-label={`${t("ask.citation.aria")} ${marker}`}
        onClick={() => onCitation(marker)}>[{marker}]</button>;
    })}
  </p>;
}

export default function AskPage() {
  const {t, locale} = useI18n();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [question, setQuestion] = useState("");
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
  const [urlConversation, setUrlConversation] = useState<string | null>(null);
  const [conversation, setConversation] = useState<Load<Conversation>>(IDLE);
  const [history, setHistory] = useState<Load<ConversationListPage>>(IDLE);
  const [activeCitation, setActiveCitation] = useState<string | null>(null);
  const [railOpen, setRailOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const questionRef = useRef<HTMLTextAreaElement>(null);

  // PRD §11 composer: auto-expand the question textarea between 64 and 180px
  // (DOM-only; never a layout-animating transition, reduced-motion safe).
  const autoGrow = useCallback(() => {
    const el = questionRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 64), 180)}px`;
  }, []);

  const loseAccess = useCallback(() => {
    setIdentity(null);
    setResearchAccess(IDLE); setCatalog(IDLE); setAnswer(IDLE);
    setResearch(IDLE); setGap(IDLE); setConversation(IDLE);
    setFileScope(null); setPickerOpen(false); setHistory(IDLE);
    setConversationId(null); setActiveCitation(null);
  }, []);

  useEffect(() => {
    fetch("/api/auth/me", {cache: "no-store"})
      .then(async response => setIdentity(
        response.ok ? await response.json() as Identity : null,
      ))
      .catch(() => setIdentity(null)).finally(() => setAuthReady(true));
    const restore = () => setUrlConversation(
      parseAskState(new URLSearchParams(location.search)).conversationId,
    );
    restore();
    addEventListener("popstate", restore);
    return () => removeEventListener("popstate", restore);
  }, []);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setRailOpen(false); setPickerOpen(false); }
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
      if (!identity || !urlConversation) { setConversation(IDLE); return; }
      setConversation({state: "loading"});
      fetch(`/api/ask/conversations/${urlConversation}`, {cache: "no-store"})
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
          setConversation({state: "ready", data: parseConversation(body)});
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
  }, [identity, urlConversation, loseAccess]);

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
    const trimmed = question.trim();
    if (!trimmed || asking) return;
    setAsking(true);
    setAnswer({state: "loading"});
    setGap(IDLE);
    setConversation(IDLE);
    setActiveCitation(null);
    setResearch(includeResearch ? {state: "loading"} : IDLE);
    if (includeResearch) {
      fetch("/api/governance/research/search", {
        method: "POST", cache: "no-store",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({query: trimmed, limit: 10}),
      }).then(async response => {
        if (response.status === 401) return loseAccess();
        const body: unknown = await response.json().catch(() => null);
        if (response.status === 403) {
          return setResearch({state: "denied", error: parseTypedError(body)});
        }
        if (!response.ok) return setResearch({state: "error", error: parseTypedError(body)});
        setResearch({state: "ready", data: parseResearchSearchEvidence(body)});
      }).catch(() => setResearch({state: "error", error: {
        code: "contract_violation", message: "", requestId: "",
      }}));
    }
    try {
      const response = await fetch("/api/ask/ask", {
        method: "POST", cache: "no-store",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({
          question: trimmed,
          ...(conversationId ? {conversation_id: conversationId} : {}),
          ...(fileScope ? {filters: {source_key: fileScope.logicalName}} : {}),
        }),
      });
      if (response.status === 401) return loseAccess();
      const body: unknown = await response.json().catch(() => null);
      if (response.status === 403) {
        return setAnswer({state: "denied", error: parseTypedError(body)});
      }
      if (!response.ok) return setAnswer({state: "error", error: parseTypedError(body)});
      const parsed = parseAskAnswer(body);
      setAnswer({state: "ready", data: parsed});
      setConversationId(parsed.conversationId);
      // URL-restorable conversation id only — never content, never storage.
      window.history.replaceState({}, "", `/ask?${askQuery(parsed.conversationId)}`);
      loadHistory();
      if (parsed.state === "honest_null" && parsed.gapId) loadGap(parsed.gapId);
    } catch {
      setAnswer({state: "error", error: {
        code: "contract_violation", message: "", requestId: "",
      }});
    } finally {
      setAsking(false);
    }
  }, [
    question, asking, includeResearch, conversationId, fileScope,
    loadGap, loadHistory, loseAccess,
  ]);

  const openCitation = useCallback((key: string) => {
    setActiveCitation(key);
    setRailOpen(true);
    requestAnimationFrame(() => focusRailEntry(key));
  }, []);

  const reopenConversation = useCallback((id: string) => {
    window.history.pushState({}, "", `/ask?${askQuery(id)}`);
    setUrlConversation(id);
    setConversationId(id);
    setAnswer(IDLE); setResearch(IDLE); setGap(IDLE);
    setActiveCitation(null);
  }, []);

  const newConversation = useCallback(() => {
    window.history.pushState({}, "", "/ask");
    setUrlConversation(null);
    setConversationId(null);
    setAnswer(IDLE); setResearch(IDLE); setGap(IDLE);
    setConversation(IDLE); setActiveCitation(null); setQuestion("");
  }, []);

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

  return <div className="ask-workspace">
    <PageHeader eyebrow={t("ask.eyebrow")} title={t("ask.title")}
      actions={<button className="ask-rail-toggle" type="button"
        onClick={() => setRailOpen(true)}>{t("ask.evidenceButton")}</button>}/>
    <div className="ask-layout">
      {/* Distinct landmark name — the grounded-answer region below carries
          "Câu trả lời"; duplicate names were an axe landmark-unique finding
          (TIP-011 Builder D, AC-10). */}
      <section className="ask-surface" aria-label={t("ask.surfaceAria")}>
        <form className="ask-form" ref={formRef} onSubmit={event => void submit(event)}>
          <label className="ask-question">{t("ask.question.label")}
            <textarea ref={questionRef} value={question} rows={1}
              placeholder={t("ask.question.placeholder")}
              onChange={event => { setQuestion(event.target.value); autoGrow(); }}
              onKeyDown={event => {
                // Enter submits; Shift+Enter inserts a newline (PRD §11).
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  formRef.current?.requestSubmit();
                }
              }}/>
          </label>
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
          <div className="action-row">
            <button type="submit" className="primary"
              disabled={!question.trim() || asking}>{t("ask.submit")}</button>
            {(conversationId || conversation.state !== "idle") && <button type="button"
              onClick={newConversation}>{t("ask.history.new")}</button>}
          </div>
        </form>

        {answer.state === "loading"
          && <p role="status" className="surface-loading">{t("ask.asking")}</p>}
        {answer.state === "denied" && <div role="alert" className="surface-denied">
          {t("surface.denied")} · {errorText(answer.error)}</div>}
        {answer.state === "error" && <div role="alert" className="surface-error">
          {t("ask.blocked")} · {errorText(answer.error)}</div>}

        {current && current.state === "grounded" && <section className="ask-answer"
          aria-label={t("ask.answer.title")}>
          <header>
            <h2>{t("ask.answer.title")}</h2>
            <p className="grounding-note">{t("ask.answer.grounded")}</p>
          </header>
          <AnswerText text={current.answer} onCitation={openCitation}/>
          {/* TIP-013B AC-4: shown ONLY when the answer is grounded on a softly
              verified fact — a small, legible double-check caveat, reachable
              as a note by keyboard/screenreader. */}
          {current.confidenceCaveat && <p className="confidence-caveat" role="note">
            {t("ask.confidenceCaveat")}</p>}
        </section>}

        {current && current.state === "honest_null" && <section className="honest-null"
          aria-label={t("ask.null.title")}>
          <h2>{t("ask.null.title")}</h2>
          <p className="honest-null-answer">{current.answer}</p>
          <p className="form-note">{t("ask.null.body")}</p>
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

        <section className="ask-history" aria-label={t("ask.history.title")}>
          <h2>{t("ask.history.title")}</h2>
          <Surface load={history} empty={t("ask.history.empty")}>{page =>
            page.items.length === 0
              ? <p className="surface-empty">{t("ask.history.empty")}</p>
              : <ol>{page.items.map(item => <li key={item.conversationId}>
                  <span className="ask-history-question">
                    <code title={item.firstQuestionDigest ?? undefined}>
                      {item.firstQuestionDigest
                        ? `${item.firstQuestionDigest.slice(0, 12)}…`
                        : item.conversationId.slice(0, 8)}
                    </code>
                  </span>
                  <small>{formatDateTime(item.lastActivityAt, locale)}</small>
                  <button type="button"
                    onClick={() => reopenConversation(item.conversationId)}>
                    {t("ask.history.reopen")}
                  </button>
                </li>)}</ol>}
          </Surface>
        </section>
      </section>

      <EvidenceRail entries={railEntries} activeKey={activeCitation}
        open={railOpen} onClose={() => setRailOpen(false)}/>
    </div>
    {railOpen && <button className="ask-scrim" type="button"
      aria-label={t("rail.close")} onClick={() => setRailOpen(false)}/>}
  </div>;
}
