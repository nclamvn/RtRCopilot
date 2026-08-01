"use client";

/**
 * The ONE shared Evidence Rail (TIP-011 Task 2, D-011-02).
 *
 * Renders typed `EvidenceEntry` items: server-provided zone chip, source and
 * revision, immutable record/document version, deep locator, evidence
 * checksums, freshness/effectiveness and policy state — every relationship
 * also carried as accessible text. The aside participates in the shell's
 * F6 region cycle (`data-shell-region`) and becomes a bottom sheet under
 * tablet width via the house `.open` pattern (page owns the scrim/toggle).
 *
 * Locator activation follows the TIP-008 deep-link contract: a same-tab
 * link to the file route with rtr.locator.v1 params; `onActivateLocator`
 * additionally notifies the page.
 */

import React from "react";
import Link from "next/link";
import type {Locator} from "../files/contracts";
import {formatNumber} from "../i18n/format";
import {MessageKey} from "../i18n/messages";
import {useI18n} from "../i18n/provider";
import {EvidenceEntry, evidenceHref, railEntryId} from "./contracts";
import {ZoneChip} from "./ZoneChip";

/** Move focus (and scroll) to one rail entry, e.g. from a citation marker. */
export function focusRailEntry(key: string) {
  document.getElementById(railEntryId(key))?.focus();
}

type Translate = (key: MessageKey) => string;

/** Accessible text equivalent for a deep locator, e.g. "Trang 4 · Ô A1". */
export function locatorText(
  locator: Locator | null,
  t: Translate,
  locale: "vi" | "en",
): string {
  if (!locator) return t("rail.locator.root");
  const parts: string[] = [];
  if (locator.page !== undefined) {
    parts.push(`${t("rail.locator.page")} ${formatNumber(locator.page, locale)}`);
  }
  if (locator.sheet !== undefined) {
    parts.push(`${t("rail.locator.sheet")} ${locator.sheet}`);
  }
  if (locator.cell !== undefined) {
    parts.push(`${t("rail.locator.cell")} ${locator.cell}`);
  }
  if (locator.slide !== undefined) {
    parts.push(`${t("rail.locator.slide")} ${formatNumber(locator.slide, locale)}`);
  }
  if (locator.t !== undefined) {
    parts.push(`${t("rail.locator.time")} ${formatNumber(locator.t / 1000, locale)}s`);
  }
  if (locator.paragraph !== undefined) {
    parts.push(`${t("rail.locator.paragraph")} ${formatNumber(locator.paragraph, locale)}`);
  }
  if (locator.table !== undefined) {
    parts.push(`${t("rail.locator.table")} ${formatNumber(locator.table, locale)}`);
  }
  if (locator.region !== undefined) {
    parts.push(`${t("rail.locator.region")} ${locator.region}`);
  }
  return parts.length > 0 ? parts.join(" · ") : t("rail.locator.root");
}

function shortHash(value: string) {
  return `${value.slice(0, 16)}…`;
}

function EntryFacts({entry}: {entry: EvidenceEntry}) {
  const {t, locale} = useI18n();
  return <dl className="rail-facts">
    <div><dt>{t("rail.zone")}</dt><dd>
      {entry.zone ? <ZoneChip zone={entry.zone}/> : t("rail.zoneUnlabeled")}
    </dd></div>
    {entry.grounding && <div><dt>{t("rail.grounding")}</dt><dd>
      {entry.grounding === "grounded"
        ? t("rail.grounding.grounded") : t("rail.grounding.research")}
    </dd></div>}
    {entry.tier && <div><dt>{t("rail.tier")}</dt>
      <dd><code>{entry.tier}</code></dd></div>}
    <div><dt>{t("rail.source")}</dt><dd>
      {entry.sourceLabel} · <code>{entry.sourceKey}</code>
      {entry.sourceRevision !== null
        && <> · {t("rail.revision")} {formatNumber(entry.sourceRevision, locale)}</>}
    </dd></div>
    <div><dt>{t("rail.record")}</dt><dd>
      <code>{entry.recordKey}</code>
      {entry.evidenceKey && <> · <code>{entry.evidenceKey}</code></>}
    </dd></div>
    {entry.recordVersionId && <div><dt>{t("rail.version")}</dt>
      <dd><code>{entry.recordVersionId}</code></dd></div>}
    {entry.versionOrdinal !== null && <div><dt>{t("rail.version")}</dt>
      <dd>{formatNumber(entry.versionOrdinal, locale)}</dd></div>}
    {entry.recordChecksum && <div><dt>{t("rail.checksum.record")}</dt>
      <dd><code title={entry.recordChecksum}>{shortHash(entry.recordChecksum)}</code></dd></div>}
    {entry.evidenceChecksums.length > 0 && <div><dt>{t("rail.checksum.evidence")}</dt>
      <dd>{entry.evidenceChecksums.map(item =>
        <code key={item} title={item}>{shortHash(item)} </code>)}</dd></div>}
    {entry.contentChecksum && <div><dt>{t("rail.checksum.content")}</dt>
      <dd><code title={entry.contentChecksum}>{shortHash(entry.contentChecksum)}</code></dd></div>}
    {entry.provenanceLevel && <div><dt>{t("rail.provenance")}</dt>
      <dd>{entry.provenanceLevel}</dd></div>}
    {entry.verificationState && <div><dt>{t("rail.verification")}</dt>
      <dd>{entry.verificationState}</dd></div>}
    {entry.freshnessState && <div><dt>{t("rail.freshness")}</dt>
      <dd>{entry.freshnessState}</dd></div>}
    {entry.corroborationState && <div><dt>{t("rail.corroboration")}</dt>
      <dd>{entry.corroborationState}</dd></div>}
    <div><dt>{t("rail.policy")}</dt><dd className={entry.redacted ? "rail-redacted" : ""}>
      {entry.redacted ? t("rail.policy.redacted") : t("rail.policy.allowed")}
    </dd></div>
  </dl>;
}

export function EvidenceRail({
  entries, activeKey, onActivateLocator, open, onClose, note, footer,
}: {
  entries: EvidenceEntry[];
  /** Key of the entry a citation currently points at (aria-current). */
  activeKey?: string | null;
  /** Locator activation callback — fires alongside the deep-link navigation. */
  onActivateLocator?: (entry: EvidenceEntry) => void;
  /** Bottom-sheet state under tablet width (house `.open` pattern). */
  open?: boolean;
  onClose?: () => void;
  note?: React.ReactNode;
  /** Surface-specific content after the entries (TIP-011 Task 3 adoption,
   *  e.g. the Documents approval timeline). */
  footer?: React.ReactNode;
}) {
  const {t, locale} = useI18n();
  return <aside id="evidence-rail" tabIndex={-1} data-shell-region
    className={`evidence-rail ${open ? "open" : ""}`} aria-label={t("rail.title")}>
    <div className="panel-heading">
      <h2>{t("rail.title")}</h2>
      {onClose && <button className="close-mobile" type="button"
        aria-label={t("rail.close")} onClick={onClose}>×</button>}
    </div>
    {note}
    {entries.length === 0 && !note && !footer
      && <p className="surface-empty">{t("rail.empty")}</p>}
    {entries.length > 0 && <ol className="rail-entries">
      {entries.map(entry => {
        const href = evidenceHref(entry);
        const position = locatorText(entry.locator, t, locale);
        return <li key={entry.key}>
          <article id={railEntryId(entry.key)} tabIndex={-1}
            aria-current={activeKey === entry.key ? "true" : undefined}
            aria-label={`${entry.marker ?? entry.recordKey} — ${entry.sourceLabel}`}>
            <header className="row-head">
              <ZoneChip zone={entry.zone}/>
              {entry.marker && <code className="rail-marker">[{entry.marker}]</code>}
              {entry.tier && <code>Tier {entry.tier}</code>}
              {entry.redacted && <code className="rail-redacted">DLP</code>}
              <strong>{entry.sourceLabel}</strong>
            </header>
            {entry.snippet && <blockquote className="rail-snippet">{entry.snippet}</blockquote>}
            <EntryFacts entry={entry}/>
            {href
              ? <Link className="rail-locator" href={href}
                  onClick={() => onActivateLocator?.(entry)}>
                  {t("rail.openLocator")} — {position}
                </Link>
              : <p className="rail-locator-none">{t("rail.noLocator")}</p>}
          </article>
        </li>;
      })}
    </ol>}
    {footer}
  </aside>;
}
