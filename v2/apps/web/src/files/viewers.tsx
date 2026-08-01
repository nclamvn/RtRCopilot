"use client";

import React, {useEffect, useMemo, useRef, useState} from "react";
import {formatNumber} from "../i18n/format";
import type {MessageKey} from "../i18n/messages";
import {useI18n} from "../i18n/provider";
import {
  Locator,
  proxyContentUrl,
  Rendition,
  ViewerManifest,
  viewerFor,
} from "./contracts";

type Props = {
  manifest: ViewerManifest;
  locator: Locator;
  onLocator: (locator: Locator) => void;
  onAccessLoss: (status: 401 | 403 | 404) => void;
};

type SearchHit = {label: string; text: string; locator: Locator};

function rendition(manifest: ViewerManifest, ...kinds: string[]) {
  return manifest.renditions.find(item => kinds.includes(item.kind));
}

/**
 * Fetches a JSON rendition. Errors are stored as catalog KEYS (not rendered
 * strings) so the surface translates them at render time — switching the
 * locale never leaves a stale-language error on screen (AC-09).
 */
function useJson(item: Rendition | undefined, onAccessLoss: Props["onAccessLoss"]) {
  const [value, setValue] = useState<unknown>();
  const [error, setError] = useState<MessageKey | "">("");
  useEffect(() => {
    let active = true;
    if (!item) return;
    if (item.byte_size > 20_000_000) {
      Promise.resolve().then(() => {
        if (active) setError("files.viewer.payloadTooLarge");
      });
      return;
    }
    fetch(proxyContentUrl(item), {cache: "no-store"})
      .then(async response => {
        if ([401, 403, 404].includes(response.status)) {
          onAccessLoss(response.status as 401 | 403 | 404);
          throw new Error("access_revoked");
        }
        if (!response.ok) throw new Error("payload_unavailable");
        const text = await response.text();
        if (text.length > 20_000_000) throw new Error("payload_too_large");
        return JSON.parse(text) as unknown;
      })
      .then(data => { if (active) setValue(data); })
      .catch(error => {
        if (active && (!(error instanceof Error) || error.message !== "access_revoked")) {
          setError("files.viewer.payloadUnreadable");
        }
      });
    return () => { active = false; };
  }, [item, onAccessLoss]);
  return {value, error};
}

function safeRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function collectHits(value: unknown, query: string): SearchHit[] {
  if (query.trim().length < 2) return [];
  const needle = query.trim().toLocaleLowerCase("vi");
  const hits: SearchHit[] = [];
  const walk = (node: unknown, context: Locator, depth: number) => {
    if (depth > 7 || hits.length >= 100) return;
    if (typeof node === "string" && node.toLocaleLowerCase("vi").includes(needle)) {
      hits.push({label: Object.entries(context).map(([k, v]) => `${k} ${v}`).join(" · "),
        text: node.slice(0, 240), locator: context});
      return;
    }
    if (Array.isArray(node)) {
      node.slice(0, 10000).forEach(item => walk(item, context, depth + 1));
      return;
    }
    const row = safeRecord(node);
    if (!row) return;
    const next = {...context};
    for (const key of ["page", "paragraph", "table", "slide", "shape", "start_ms"]) {
      if (typeof row[key] === "number") {
        const locatorKey = key === "start_ms" ? "t" : key;
        Object.assign(next, {[locatorKey]: row[key]});
      }
    }
    if (typeof row.sheet === "string") next.sheet = row.sheet;
    if (typeof row.cell === "string") next.cell = row.cell;
    if (typeof row.region === "string") next.region = row.region;
    Object.values(row).forEach(item => walk(item, next, depth + 1));
  };
  walk(value, {}, 0);
  return hits;
}

function SearchPanel({payload, onLocator}: {payload: unknown; onLocator: Props["onLocator"]}) {
  const {t, locale} = useI18n();
  const [query, setQuery] = useState("");
  const hits = useMemo(() => collectHits(payload, query), [payload, query]);
  return <section className="within-search" aria-label={t("files.viewer.searchLabel")}>
    <label htmlFor="within-query">{t("files.viewer.searchLabel")}</label>
    <input id="within-query" value={query} onChange={event => setQuery(event.target.value)}
      placeholder={t("files.viewer.searchPlaceholder")}/>
    {query.length >= 2 && <p className="result-note" aria-live="polite">
      {formatNumber(hits.length, locale)} {t("files.viewer.searchResults")}
    </p>}
    <ol className="search-hits">
      {hits.map((hit, index) => <li key={`${hit.label}-${index}`}>
        <button type="button" onClick={() => onLocator(hit.locator)}>
          <small>{hit.label || t("files.viewer.searchFallback")}</small><span>{hit.text}</span>
        </button>
      </li>)}
    </ol>
  </section>;
}

function PdfSurface({
  manifest, locator, onLocator, onAccessLoss, office,
}: Props & {office?: boolean}) {
  const {t, locale} = useI18n();
  const preview = rendition(manifest, "preview_pdf");
  const textItem = rendition(manifest, "page_text_json", "structured_text_json");
  const {value, error} = useJson(textItem, onAccessLoss);
  if (!preview) return <Partial reason={t("files.viewer.noPdf")}/>;
  const page = locator.page ?? locator.slide ?? 1;
  return <div className="viewer-split">
    <div className="pdf-stage">
      {office && <p className="fidelity">{t("files.viewer.fidelity")}</p>}
      <iframe title={t("files.viewer.pdfTitle")}
        src={`${proxyContentUrl(preview)}#page=${page}`}/>
    </div>
    <div className="viewer-tools">
      <div className="pager">
        <button type="button" onClick={() => onLocator({page: Math.max(1, page - 1)})}>
          {t("files.viewer.prevPage")}</button>
        <output>{t("rail.locator.page")} {formatNumber(page, locale)}</output>
        <button type="button" onClick={() => onLocator({page: page + 1})}>
          {t("files.viewer.nextPage")}</button>
      </div>
      {error ? <p role="status">{t(error)}</p> : <SearchPanel payload={value} onLocator={onLocator}/>}
    </div>
  </div>;
}

function ImageViewer(props: Props) {
  const {t} = useI18n();
  const image = rendition(props.manifest, "safe_image_preview");
  const ocr = rendition(props.manifest, "ocr_json");
  const {value, error} = useJson(ocr, props.onAccessLoss);
  const [actual, setActual] = useState(false);
  if (!image) return <Partial reason={t("files.viewer.noImage")}/>;
  return <div className="viewer-split">
    <div className={`image-stage ${actual ? "actual" : ""}`}>
      {/* Safe authenticated rendition URLs cannot use the Next image optimizer. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={proxyContentUrl(image)} alt={t("files.viewer.imageAlt")}/>
      {props.locator.region && <span className="region-indicator">
        {t("files.viewer.region")} {props.locator.region}</span>}
    </div>
    <div className="viewer-tools">
      <button type="button" onClick={() => setActual(value => !value)}>
        {actual ? t("files.viewer.fit") : t("files.viewer.actualSize")}
      </button>
      {error ? <p role="status">{t(error)}</p>
        : <SearchPanel payload={value} onLocator={props.onLocator}/>}
    </div>
  </div>;
}

function SheetViewer(props: Props) {
  const {t} = useI18n();
  const preview = rendition(props.manifest, "sheet_preview_json");
  const {value, error} = useJson(preview, props.onAccessLoss);
  const root = safeRecord(value);
  const sheets = Array.isArray(root?.sheets) ? root.sheets.slice(0, 100) : [];
  const firstName = String(safeRecord(sheets[0])?.sheet ?? "");
  const requestedSheet = props.locator.sheet;
  const activeName = requestedSheet && sheets.some(
    item => safeRecord(item)?.sheet === requestedSheet,
  ) ? requestedSheet : firstName;
  const selected = safeRecord(
    sheets.find(item => safeRecord(item)?.sheet === activeName) ?? sheets[0],
  );
  if (error) return <Partial reason={t(error)}/>;
  if (!root) return <p className="loading" role="status">{t("files.viewer.sheetLoading")}</p>;
  const rows = Array.isArray(selected?.rows) ? selected.rows.slice(0, 5000) : [];
  const mergedRanges = Array.isArray(selected?.merged_ranges)
    ? selected.merged_ranges.filter(item => typeof item === "string").slice(0, 100)
    : [];
  return <div className="sheet-layout">
    <div className="sheet-tabs" role="tablist" aria-label={t("files.viewer.sheetTabs")}>
      {sheets.map(item => {
        const name = String(safeRecord(item)?.sheet ?? "");
        return <button type="button" role="tab" aria-selected={name === activeName}
          key={name} onClick={() => props.onLocator({sheet: name})}>{name}</button>;
      })}
    </div>
    <div className="sheet-grid" role="region" aria-label={t("files.viewer.sheetGrid")} tabIndex={0}>
      {mergedRanges.length > 0 && <p className="merged-ranges">
        {t("files.viewer.mergedRanges")} {mergedRanges.join(", ")}
      </p>}
      <table><tbody>{rows.map((row, rowIndex) => {
        const rowData = safeRecord(row);
        const cells = Array.isArray(rowData?.cells) ? rowData.cells.slice(0, 1000) : [];
        return <tr key={rowIndex}><th scope="row">{String(rowData?.row ?? rowIndex + 1)}</th>
          {cells.map((cell, cellIndex) => {
            const data = safeRecord(cell);
            const coordinate = String(data?.cell ?? "");
            const formula = typeof data?.formula === "string" ? data.formula : null;
            return <td key={coordinate || cellIndex} className={
          props.locator.sheet === activeName && props.locator.cell === coordinate ? "active-cell" : ""
            }><button type="button" onClick={() => props.onLocator({sheet: activeName, cell: coordinate})}>
              <span>{String(data?.value ?? "")}</span>
              {formula && <code title={t("files.viewer.formula")}>{formula}</code>}
            </button></td>;
          })}</tr>;
      })}</tbody></table>
    </div>
    <SearchPanel payload={value} onLocator={props.onLocator}/>
  </div>;
}

function MediaViewer(props: Props & {video: boolean}) {
  const {t} = useI18n();
  const mediaItem = rendition(props.manifest, props.video ? "browser_video" : "browser_audio");
  const poster = rendition(props.manifest, props.video ? "poster" : "waveform");
  const transcript = rendition(props.manifest, "transcript_json");
  const {value, error} = useJson(transcript, props.onAccessLoss);
  const ref = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  useEffect(() => {
    if (ref.current && props.locator.t !== undefined) ref.current.currentTime = props.locator.t / 1000;
  }, [props.locator.t]);
  if (!mediaItem) return <Partial reason={t("files.viewer.noMedia")}/>;
  const common = {
    ref,
    controls: true,
    preload: "metadata" as const,
    src: proxyContentUrl(mediaItem),
    onTimeUpdate: () => {
      const milliseconds = Math.floor((ref.current?.currentTime ?? 0) * 1000);
      if (milliseconds % 1000 < 250) props.onLocator({t: milliseconds});
    },
  };
  return <div className="media-layout">
    <div className="media-stage">
      {props.video
        ? <video {...common} poster={poster ? proxyContentUrl(poster) : undefined}/>
        : <><audio {...common}/>{poster &&
          /* Safe authenticated rendition URLs cannot use the Next image optimizer. */
          // eslint-disable-next-line @next/next/no-img-element
          <img className="waveform" src={proxyContentUrl(poster)}
            alt={t("files.viewer.waveformAlt")}/>}</>}
    </div>
    {error ? <p role="status">{t(error)}</p>
      : <SearchPanel payload={value} onLocator={props.onLocator}/>}
  </div>;
}

function Partial({reason}: {reason: string}) {
  const {t} = useI18n();
  return <div className="partial" role="status">
    <strong>{t("files.viewer.partial")}</strong><p>{reason}</p></div>;
}

export function FileViewer(props: Props) {
  const {t} = useI18n();
  const kind = viewerFor(props.manifest.viewer_kind);
  if (kind === "image") return <ImageViewer {...props}/>;
  if (kind === "pdf") return <PdfSurface {...props}/>;
  if (kind === "docx" || kind === "pptx") return <PdfSurface {...props} office/>;
  if (kind === "xlsx") return <SheetViewer {...props}/>;
  if (kind === "video") return <MediaViewer {...props} video/>;
  if (kind === "audio") return <MediaViewer {...props} video={false}/>;
  return <Partial reason={t("files.viewer.unsupported")}/>;
}
