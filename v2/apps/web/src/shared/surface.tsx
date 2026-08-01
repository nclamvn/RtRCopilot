"use client";

/**
 * Canonical home of the typed-error surface (TIP-011 Task 1, extracted from
 * Builder 4b's Knowledge Ops implementation). Every workspace renders
 * `error.code · request_id` identically through `Surface`/`errorText`;
 * 401 drops the session at the caller (`loseAccess` pattern), 403 renders the
 * denied state here WITHOUT dropping the session.
 *
 * Builders B/C: import `Surface`, `errorText`, `Load`, `IDLE`,
 * `parseTypedError` and `TypedError` from this module — not from
 * `governance/contracts` or page-local copies.
 */

import React from "react";
import {TypedError} from "../governance/contracts";
import {useI18n} from "../i18n/provider";

export {parseTypedError} from "../governance/contracts";
export type {TypedError} from "../governance/contracts";

export type Load<T> =
  | {state: "idle"}
  | {state: "loading"}
  | {state: "ready"; data: T}
  | {state: "denied"; error: TypedError}
  | {state: "error"; error: TypedError};

export const IDLE = {state: "idle"} as const;

export function errorText(error: TypedError) {
  return error.requestId ? `${error.code} · ${error.requestId}` : error.code;
}

export function Surface<T>({load, children, empty, retry}: {
  load: Load<T>; empty?: string; retry?: () => void;
  children: (data: T) => React.ReactNode;
}) {
  const {t} = useI18n();
  if (load.state === "idle" || load.state === "loading") {
    return <p role="status" className="surface-loading">{t("surface.loading")}</p>;
  }
  if (load.state === "denied") {
    return <div role="alert" className="surface-denied">
      {t("surface.denied")} · {errorText(load.error)}
    </div>;
  }
  if (load.state === "error") {
    return <div role="alert" className="surface-error">
      {t("surface.error")} · {errorText(load.error)}
      {retry && <button type="button" onClick={retry}>{t("surface.retry")}</button>}
    </div>;
  }
  const isEmpty = Array.isArray(load.data) && load.data.length === 0;
  if (isEmpty && empty) return <p className="surface-empty">{empty}</p>;
  return <>{children(load.data)}</>;
}
