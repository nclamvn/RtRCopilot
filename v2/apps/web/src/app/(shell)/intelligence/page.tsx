"use client";

import Link from "next/link";
import React, {useCallback, useEffect, useMemo, useState} from "react";
import {
  IntelligenceBriefing,
  IntelligenceItem,
  parseIntelligenceBriefing,
} from "../../../intelligence/contracts";
import {formatDateTime} from "../../../i18n/format";
import {useI18n} from "../../../i18n/provider";
import {Icon} from "../../../shell/Icon";
import {PageHeader} from "../../../shell/AppShell";

type Identity = {user_id: string; email: string; display_name: string; roles: string[]};
type BriefState =
  | {state: "idle" | "loading"}
  | {state: "ready"; data: IntelligenceBriefing}
  | {state: "denied" | "error"};

function itemSummary(item: IntelligenceItem, attentionText: string) {
  return item.kind === "attention" ? attentionText : item.summary;
}

export default function IntelligencePage() {
  const {t, locale} = useI18n();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [brief, setBrief] = useState<BriefState>({state: "idle"});
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBrief({state: "loading"});
    try {
      const response = await fetch(
        "/api/governance/intelligence/briefing?limit=16",
        {cache: "no-store"},
      );
      if (response.status === 401) {
        setIdentity(null);
        setBrief({state: "idle"});
        return;
      }
      if (response.status === 403) {
        setBrief({state: "denied"});
        return;
      }
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setBrief({state: "error"});
        return;
      }
      const parsed = parseIntelligenceBriefing(body);
      setBrief({state: "ready", data: parsed});
      setSelectedId(current => (
        current && parsed.items.some(item => item.itemId === current)
          ? current : parsed.items[0]?.itemId ?? null
      ));
    } catch {
      setBrief({state: "error"});
    }
  }, []);

  useEffect(() => {
    let active = true;
    fetch("/api/auth/me", {cache: "no-store"})
      .then(async response => {
        if (active) setIdentity(response.ok ? await response.json() as Identity : null);
      })
      .catch(() => { if (active) setIdentity(null); })
      .finally(() => { if (active) setAuthReady(true); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!identity) return;
    const timer = setTimeout(() => { void load(); }, 0);
    return () => clearTimeout(timer);
  }, [identity, load]);

  const selected = useMemo(() => (
    brief.state === "ready"
      ? brief.data.items.find(item => item.itemId === selectedId) ?? null
      : null
  ), [brief, selectedId]);

  return <div className="intelligence-workspace">
    <PageHeader eyebrow={t("intelligence.eyebrow")} title={t("intelligence.title")}
      actions={<button type="button" className="intelligence-refresh"
        aria-label={t("intelligence.refresh")}
        onClick={() => void load()} disabled={!identity || brief.state === "loading"}>
        <span>{t("intelligence.refresh")}</span>
        <Icon name="recent" size={15}/>
      </button>}/>

    {!authReady && <p className="intelligence-state" role="status">
      {t("shell.sessionChecking")}
    </p>}
    {authReady && !identity && <section className="intelligence-gate">
      <p>{t("intelligence.gate")}</p>
      <Link href="/api/auth/login">{t("shell.login")}</Link>
    </section>}
    {identity && brief.state === "loading" && <div className="intelligence-loading"
      role="status" aria-live="polite">
      <span aria-hidden/><p>{t("intelligence.loading")}</p>
    </div>}
    {identity && (brief.state === "error" || brief.state === "denied")
      && <section className="intelligence-error" role="alert">
        <p>{brief.state === "denied" ? t("surface.denied") : t("intelligence.error")}</p>
        <button type="button" onClick={() => void load()}>{t("surface.retry")}</button>
      </section>}
    {identity && brief.state === "ready" && <>
      <div className="intelligence-summary" aria-label={t("intelligence.summary")}>
        <p>{t("intelligence.summary")}</p>
        <dl>
          <div><dt>{t("intelligence.count.update")}</dt>
            <dd>{brief.data.counts.updates}</dd></div>
          <div><dt>{t("intelligence.count.attention")}</dt>
            <dd>{brief.data.counts.attention}</dd></div>
          <div><dt>{t("intelligence.count.research")}</dt>
            <dd>{brief.data.counts.research}</dd></div>
        </dl>
        <time dateTime={brief.data.generatedAt}>
          {t("intelligence.updated")} {formatDateTime(brief.data.generatedAt, locale)}
        </time>
      </div>

      {brief.data.items.length === 0
        ? <section className="intelligence-empty">
            <h2>{t("intelligence.empty.title")}</h2>
            <p>{t("intelligence.empty.body")}</p>
          </section>
        : <div className="intelligence-layout">
          <section className="intelligence-feed" aria-label={t("intelligence.title")}
            data-shell-region tabIndex={-1}>
            <ol>
              {brief.data.items.map(item => <li key={item.itemId}
                data-zone={item.zoneLabel} data-priority={item.priority}>
                <span className="intelligence-node" aria-hidden/>
                <article>
                  <div className="intelligence-item-meta">
                    <span>{t(item.zoneLabel === "sot"
                      ? "intelligence.zone.sot" : "intelligence.zone.research")}</span>
                    <span>{t(item.kind === "update" ? "intelligence.kind.update"
                      : item.kind === "attention" ? "intelligence.kind.attention"
                        : "intelligence.kind.research")}</span>
                    <time dateTime={item.observedAt}>
                      {formatDateTime(item.observedAt, locale)}
                    </time>
                  </div>
                  <button type="button" className="intelligence-item-select"
                    aria-current={selectedId === item.itemId ? "true" : undefined}
                    onClick={() => setSelectedId(item.itemId)}>
                    <span className="intelligence-item-title">{item.title}</span>
                    <span className="intelligence-item-summary">
                      {itemSummary(item, t("intelligence.attention.summary"))}
                    </span>
                  </button>
                  <div className="intelligence-item-actions">
                    <span>{item.evidence.sourceLabel}</span>
                    <Link href={`/ask?q=${encodeURIComponent(item.askQuery)}`}>
                      {t("intelligence.ask")} <Icon name="arrowRight" size={14}/>
                    </Link>
                  </div>
                </article>
              </li>)}
            </ol>
          </section>

          <aside className="intelligence-rail" aria-label={t("intelligence.source")}
            data-shell-region tabIndex={-1}>
            {selected && <>
              <div className="intelligence-rail-head">
                <p>{t("intelligence.source")}</p>
                <span>{t(selected.zoneLabel === "sot"
                  ? "intelligence.zone.sot" : "intelligence.zone.research")}</span>
              </div>
              <h2>{selected.title}</h2>
              <dl>
                <div><dt>{t("intelligence.source")}</dt>
                  <dd>{selected.evidence.sourceLabel}</dd></div>
                <div><dt>{t("intelligence.record")}</dt>
                  <dd><code>{selected.evidence.recordKey}</code></dd></div>
                <div><dt>{t("intelligence.observed")}</dt>
                  <dd>{formatDateTime(selected.observedAt, locale)}</dd></div>
                {selected.evidence.verificationState && <div>
                  <dt>{t("intelligence.verification")}</dt>
                  <dd>{selected.evidence.verificationState}</dd></div>}
                {selected.evidence.freshnessState && <div>
                  <dt>{t("intelligence.freshness")}</dt>
                  <dd>{selected.evidence.freshnessState}</dd></div>}
                {selected.evidence.corroborationState && <div>
                  <dt>{t("intelligence.corroboration")}</dt>
                  <dd>{selected.evidence.corroborationState}</dd></div>}
                <div><dt>{t("intelligence.checksum")}</dt>
                  <dd><code>{selected.evidence.contentSha256.slice(0, 16)}…</code></dd></div>
              </dl>
              <Link className="intelligence-rail-ask"
                href={`/ask?q=${encodeURIComponent(selected.askQuery)}`}>
                {t("intelligence.ask")} <Icon name="arrowRight" size={15}/>
              </Link>
            </>}
          </aside>
        </div>}
    </>}
  </div>;
}
