import React from "react";

/**
 * Dependency-free icon set — Lucide 24×24 path data rendered inline so the
 * frozen offline Docker build never adds a runtime package (PRD icon list,
 * stroke 1.75, currentColor). Decorative by default (aria-hidden); pass a
 * `title` only when the icon is the sole label of an interactive control.
 */

export type IconName =
  | "ask" | "files" | "documents" | "knowledge" | "operations" | "admin"
  | "recent" | "search" | "moon" | "sun" | "languages" | "send" | "citation"
  | "plus" | "panelLeft" | "chevrons" | "logout" | "arrowRight";

const PATHS: Record<IconName, React.ReactNode> = {
  ask: <>
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    <path d="M13 8H7"/><path d="M17 12H7"/>
  </>,
  files: <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>,
  documents: <>
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>
    <path d="M14 2v4a2 2 0 0 0 2 2h4"/>
    <path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>
  </>,
  knowledge: <>
    <path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1"/>
    <path d="M16 21h1a2 2 0 0 0 2-2v-5a2 2 0 0 1 2-2 2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"/>
  </>,
  operations: <>
    <path d="M6 20v-4"/><path d="M12 20V10"/><path d="M18 20V4"/>
  </>,
  admin: <>
    <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>
    <path d="m9 12 2 2 4-4"/>
  </>,
  recent: <>
    <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
  </>,
  search: <>
    <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
  </>,
  moon: <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>,
  sun: <>
    <circle cx="12" cy="12" r="4"/>
    <path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/>
    <path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/>
    <path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
  </>,
  languages: <>
    <path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/>
    <path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>
  </>,
  send: <>
    <path d="M22 2 11 13"/><path d="M22 2 15 22 11 13 2 9 22 2Z"/>
  </>,
  citation: <>
    <path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 1 1 0 10h-2"/>
    <line x1="8" x2="16" y1="12" y2="12"/>
  </>,
  plus: <><path d="M5 12h14"/><path d="M12 5v14"/></>,
  panelLeft: <>
    <rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>
  </>,
  chevrons: <>
    <path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>
  </>,
  logout: <>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
    <path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>
  </>,
  arrowRight: <><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></>,
};

export function Icon({name, size = 18, className}: {
  name: IconName; size?: number; className?: string;
}) {
  return <svg className={className} width={size} height={size}
    viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    focusable="false">{PATHS[name]}</svg>;
}
