"use client";

import React, {useEffect, useState} from "react";

type Status = {ok: boolean; status: string; dependencies?: Record<string, string>; request_id?: string};
type Identity = {user_id: string; email: string; display_name: string; roles: string[]};

export default function Home() {
  const [status, setStatus] = useState<Status>({ok: false, status: "checking"});
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  useEffect(() => {
    fetch("/api/status").then(async response => {
      const data = await response.json() as Status;
      setStatus({...data, ok: response.ok && data.ok});
    }).catch(() => setStatus({ok: false, status: "unreachable"}));
    fetch("/api/auth/me", {cache: "no-store"}).then(async response => {
      setIdentity(response.ok ? await response.json() as Identity : null);
      setAuthReady(true);
    }).catch(() => setAuthReady(true));
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", {method: "POST"});
    setIdentity(null);
  }

  return (
    <main>
      <header><span className="mark">RT</span><span>RT ROBOTICS</span></header>
      <section>
        <p className="eyebrow">Production platform scaffold</p>
        <h1>V2 foundation <em>· chưa có dữ liệu</em></h1>
        <p className="lede">Đây là lớp hạ tầng an toàn cho RtR Copilot. Ask, Files và Documents
          chỉ xuất hiện sau khi identity, policy và nguồn dữ liệu vượt acceptance gate.</p>
        <div className="status" aria-live="polite">
          <div><span className={status.ok ? "dot ok" : "dot"}/><b>{status.status}</b></div>
          <dl>
            {Object.entries(status.dependencies ?? {}).map(([name, value]) =>
              <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}
          </dl>
          {status.request_id && <small>Request {status.request_id}</small>}
        </div>
        <div className="actions">
          {authReady && identity
            ? <>
                <div className="identity">
                  <strong>{identity.display_name || identity.email}</strong>
                  <span>{identity.email} · {identity.roles.join(", ")}</span>
                </div>
                <button type="button" onClick={logout}>Đăng xuất</button>
              </>
            : authReady
              ? <>
                  {/* Full navigation is required for the external OIDC redirect chain. */}
                  {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
                  <a className="primary" href="/api/auth/login">Đăng nhập công ty</a>
                </>
              : <span className="auth-loading">Đang kiểm tra phiên…</span>}
          <a href="/api/status">Kiểm tra readiness<span aria-hidden> ↗</span></a>
        </div>
      </section>
    </main>
  );
}
