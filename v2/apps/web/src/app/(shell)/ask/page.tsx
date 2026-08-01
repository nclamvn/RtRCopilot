"use client";

import React from "react";
import {useI18n} from "../../../i18n/provider";
import {PageHeader} from "../../../shell/AppShell";

/** Placeholder Ask surface — Builder B (TIP-011 Task 2) replaces the body. */
export default function AskPage() {
  const {t} = useI18n();
  return <>
    <PageHeader eyebrow={t("ask.eyebrow")} title={t("ask.title")}/>
    <section className="placeholder-card">
      <p>{t("ask.comingSoon")}</p>
      <p className="form-note">{t("ask.note")}</p>
    </section>
  </>;
}
