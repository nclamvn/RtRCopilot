"use client";

import React from "react";
import {MessageKey} from "../../../i18n/messages";
import {useI18n} from "../../../i18n/provider";
import {PageHeader} from "../../../shell/AppShell";

/**
 * Placeholder Admin area. No admin UI exists yet (checked: the backend ships
 * `/api/v1/admin/*` and the governance proxy already allowlists the `admin`
 * family, but no page consumed it). This lists the existing admin API
 * surface areas until a real admin workspace is commissioned.
 */
const ADMIN_SURFACES: ReadonlyArray<{labelKey: MessageKey; path: string}> = [
  {labelKey: "admin.api.sources", path: "/api/v1/admin/research-sources"},
  {labelKey: "admin.api.settings", path: "/api/v1/admin/settings"},
  {labelKey: "admin.api.gapPriority", path: "/api/v1/admin/gaps/{gap_id}/priority"},
  {labelKey: "admin.api.subjects", path: "/api/v1/admin/subjects"},
  {labelKey: "admin.api.jobs", path: "/api/v1/admin/jobs/health"},
];

export default function AdminPage() {
  const {t} = useI18n();
  return <>
    <PageHeader eyebrow={t("admin.eyebrow")} title={t("admin.title")}/>
    <section className="placeholder-card">
      <p>{t("admin.comingSoon")}</p>
      <ul>
        {ADMIN_SURFACES.map(item => <li key={item.path}>
          {t(item.labelKey)}<code>{item.path}</code>
        </li>)}
      </ul>
    </section>
  </>;
}
