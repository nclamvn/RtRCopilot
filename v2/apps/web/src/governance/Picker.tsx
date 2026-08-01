"use client";

/**
 * TIP-011 Task 4 — typeahead pickers over the policy-filtered picker
 * endpoints (`/api/v1/governance/pickers/subjects|records`, AC-06), consumed
 * by the Knowledge Ops assign and gap-answer forms.
 *
 * WAI-ARIA combobox pattern: the text input is a `combobox` controlling a
 * `listbox` popup; ArrowDown/ArrowUp move `aria-activedescendant`, Enter
 * selects, Escape closes. Results are debounced, bounded (limit 8) and render
 * ONLY what the backend disclosed — zone chips come from the literal server
 * `zone_label` (a forged label rejects the whole page in the parser).
 * Typed loading/denied/error/empty states mirror the shared Surface
 * semantics; 401 drops the session via `onSessionLost`.
 *
 * For the record picker a raw version-UUID stays usable as a fallback: a
 * UUID-shaped query offers a "use this UUID directly" option (curators may
 * carry a version id straight from the publish gate).
 */

import React, {useEffect, useId, useRef, useState} from "react";
import type {MessageKey} from "../i18n/messages";
import {useI18n} from "../i18n/provider";
import {ZoneChip} from "../rail/ZoneChip";
import {
  errorText,
  IDLE,
  parseTypedError,
  type Load,
} from "../shared/surface";
import {parseRecordPickerPage, parseSubjectPickerPage} from "./contracts";

export type PickerKind = "subjects" | "records";
export type PickerSelection = {id: string; label: string};
export type PickerOption = {
  id: string;
  label: string;
  sublabel: string | null;
  zone: "sot" | null;
  raw: boolean;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DEBOUNCE_MS = 200;
const LIMIT = 8;

const LABELS: Record<PickerKind, {label: MessageKey; placeholder: MessageKey}> = {
  subjects: {label: "picker.subjectLabel", placeholder: "picker.subjectPlaceholder"},
  records: {label: "picker.recordLabel", placeholder: "picker.recordPlaceholder"},
};

function mapOptions(kind: PickerKind, body: unknown): PickerOption[] {
  if (kind === "subjects") {
    return parseSubjectPickerPage(body).items.map(item => ({
      id: item.subject_id,
      label: item.display_name,
      sublabel: item.email,
      zone: null,
      raw: false,
    }));
  }
  return parseRecordPickerPage(body).items.map(item => ({
    id: item.record_version_id,
    label: item.record_key,
    sublabel: item.title ? `${item.title} · ${item.classification}` : item.classification,
    zone: item.zone_label,
    raw: false,
  }));
}

export function PickerCombobox({kind, value, onSelect, onSessionLost}: {
  kind: PickerKind;
  value: PickerSelection | null;
  onSelect: (selection: PickerSelection | null) => void;
  onSessionLost: () => void;
}) {
  const {t} = useI18n();
  const reactId = useId();
  const inputId = `picker-${kind}-${reactId}`;
  const listboxId = `${inputId}-listbox`;
  const rootRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<Load<PickerOption[]>>(IDLE);
  // Requested highlight index; the rendered index is clamped to the current
  // option list, so no state sync is needed when results change.
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (!open) return;
    const trimmed = query.trim();
    let live = true;
    const timer = setTimeout(() => {
      if (!trimmed) {
        setResults(IDLE);
        return;
      }
      setResults({state: "loading"});
      const params = new URLSearchParams({query: trimmed, limit: String(LIMIT)});
      fetch(`/api/governance/governance/pickers/${kind}?${params}`, {cache: "no-store"})
        .then(async response => {
          if (!live) return;
          if (response.status === 401) return onSessionLost();
          const body: unknown = await response.json().catch(() => null);
          if (response.status === 403) {
            return setResults({state: "denied", error: parseTypedError(body)});
          }
          if (!response.ok) {
            return setResults({state: "error", error: parseTypedError(body)});
          }
          setResults({state: "ready", data: mapOptions(kind, body)});
        })
        .catch(() => {
          if (live) {
            setResults({state: "error", error: {
              code: "contract_violation", message: "", requestId: "",
            }});
          }
        });
    }, trimmed ? DEBOUNCE_MS : 0);
    return () => { live = false; clearTimeout(timer); };
  }, [open, query, kind, onSessionLost]);

  const trimmed = query.trim();
  const fetched = results.state === "ready" ? results.data : [];
  const rawOption: PickerOption | null = kind === "records" && UUID.test(trimmed)
    ? {id: trimmed, label: trimmed, sublabel: null, zone: null, raw: true}
    : null;
  const options = rawOption ? [rawOption, ...fetched] : fetched;
  const activeIndex = options.length === 0
    ? -1 : Math.min(Math.max(active, 0), options.length - 1);

  const select = (option: PickerOption) => {
    onSelect({id: option.id, label: option.label});
    setOpen(false);
    setQuery("");
    setResults(IDLE);
    setActive(0);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive(Math.min(activeIndex + 1, options.length - 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive(Math.max(activeIndex - 1, 0));
      return;
    }
    if (event.key === "Enter") {
      if (open && activeIndex >= 0 && options[activeIndex]) {
        event.preventDefault();
        select(options[activeIndex]);
      }
      return;
    }
    if (event.key === "Escape") setOpen(false);
  };

  const optionId = (index: number) => `${inputId}-option-${index}`;
  const labels = LABELS[kind];

  return <div ref={rootRef} className="picker"
    onBlur={event => {
      if (!rootRef.current?.contains(event.relatedTarget as Node | null)) {
        setOpen(false);
      }
    }}>
    <label htmlFor={inputId}>{t(labels.label)}</label>
    {value && <p className="picker-selected">
      <span>{t("picker.selected")}:</span> <code>{value.label}</code>
      <button type="button" onClick={() => onSelect(null)}>{t("picker.clear")}</button>
    </p>}
    <input id={inputId} type="text" role="combobox" autoComplete="off"
      aria-expanded={open} aria-autocomplete="list"
      aria-controls={open ? listboxId : undefined}
      aria-activedescendant={open && activeIndex >= 0 && options[activeIndex]
        ? optionId(activeIndex) : undefined}
      value={query} placeholder={t(labels.placeholder)}
      onChange={event => { setQuery(event.target.value); setOpen(true); }}
      onFocus={() => setOpen(true)}
      onKeyDown={onKeyDown}/>
    {open && <div className="picker-pop">
      {trimmed.length === 0 && <p className="form-note">{t("picker.hint")}</p>}
      {results.state === "loading"
        && <p role="status" className="surface-loading">{t("picker.loading")}</p>}
      {results.state === "denied" && <p role="alert" className="surface-denied">
        {t("surface.denied")} · {errorText(results.error)}</p>}
      {results.state === "error" && <p role="alert" className="surface-error">
        {t("surface.error")} · {errorText(results.error)}</p>}
      {results.state === "ready" && options.length === 0 && trimmed.length > 0
        && <p className="surface-empty">{t("picker.empty")}</p>}
      <ul role="listbox" id={listboxId} aria-label={t(labels.label)}
        className="picker-options">
        {options.map((option, index) => <li key={`${option.id}-${option.raw}`}
          id={optionId(index)} role="option"
          aria-selected={index === activeIndex}
          className={index === activeIndex ? "picker-option active" : "picker-option"}
          onMouseDown={event => { event.preventDefault(); select(option); }}>
          <span className="row-head">
            {option.zone && <ZoneChip zone={option.zone}/>}
            <strong>{option.raw ? t("picker.useRawId") : option.label}</strong>
          </span>
          {option.raw
            ? <code>{option.id}</code>
            : option.sublabel && <small>{option.sublabel}</small>}
        </li>)}
      </ul>
    </div>}
  </div>;
}
