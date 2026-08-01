"use client";

/**
 * Files workspace (TIP-008), living inside the unified shell since TIP-011:
 * the AppShell owns the topbar/nav/`<main>`; this page renders ONE
 * `PageHeader`, the catalog + safe-viewer surface, and the SHARED Evidence
 * Rail (`src/rail`) fed by the manifest adapter. Deep-link URLs are minted
 * against `/files` (rtr.locator.v1 params preserved on restore).
 */

import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {
  FileItem,
  Locator,
  locatorQuery,
  parseLocator,
  parseManifest,
  ViewerKind,
  ViewerManifest,
} from "../../../files/contracts";
import {manifestEvidence} from "../../../files/evidence";
import {FileViewer} from "../../../files/viewers";
import {useI18n} from "../../../i18n/provider";
import {EvidenceRail} from "../../../rail/EvidenceRail";
import {PageHeader} from "../../../shell/AppShell";

type Status = {ok: boolean; status: string; dependencies?: Record<string, string>; request_id?: string};
type Identity = {user_id: string; email: string; display_name: string; roles: string[]};
type CatalogPage = {items: FileItem[]; next_cursor?: string | null};
type UploadTarget = {target_id: string; label: string; classification: string};
type UploadStatus = {
  upload_id: string; job_id: string; state: string; progress: number; retryable: boolean;
  error_code?: string | null; failed_stage?: string | null; version_id?: string | null;
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TYPES: Array<{value: "" | ViewerKind; label: string}> = [
  {value: "", label: "Tất cả"}, {value: "image", label: "Ảnh"},
  {value: "pdf", label: "PDF"}, {value: "docx", label: "DOCX"},
  {value: "xlsx", label: "XLSX"}, {value: "pptx", label: "PPTX"},
  {value: "video", label: "Video"}, {value: "audio", label: "Audio"},
];

function readableBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export default function FilesPage() {
  const {t} = useI18n();
  const [status, setStatus] = useState<Status>({ok: false, status: "checking"});
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [files, setFiles] = useState<FileItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [catalogState, setCatalogState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"" | ViewerKind>("");
  const [selected, setSelected] = useState<string | null>(null);
  const [manifest, setManifest] = useState<ViewerManifest | null>(null);
  const [viewerError, setViewerError] = useState("");
  const [locator, setLocator] = useState<Locator>({});
  const [targets, setTargets] = useState<UploadTarget[]>([]);
  const [upload, setUpload] = useState<UploadStatus | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const pollAbort = useRef<AbortController | null>(null);
  const revalidateAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/status").then(async response => {
        const data = await response.json() as Status;
        setStatus({...data, ok: response.ok && data.ok});
      }).catch(() => setStatus({ok: false, status: "unreachable"})),
      fetch("/api/auth/me", {cache: "no-store"}).then(async response => {
        setIdentity(response.ok ? await response.json() as Identity : null);
      }).catch(() => setIdentity(null)).finally(() => setAuthReady(true)),
    ]);
    const restore = () => {
      const params = new URLSearchParams(location.search);
      const version = params.get("version");
      setSelected(version && UUID.test(version) ? version : null);
      setLocator(parseLocator(params));
    };
    restore();
    addEventListener("popstate", restore);
    return () => removeEventListener("popstate", restore);
  }, []);

  const clearSelection = useCallback(() => {
    setSelected(null);
    setManifest(null);
    setViewerError("");
    setLocator({});
    history.replaceState({}, "", "/files");
  }, []);

  const handleAccessLoss = useCallback((responseStatus: 401 | 403 | 404) => {
    if (responseStatus === 404) {
      clearSelection();
      return;
    }
    pollAbort.current?.abort();
    revalidateAbort.current?.abort();
    setIdentity(null);
    setFiles([]);
    setCursor(null);
    setCatalogState("idle");
    setTargets([]);
    setUpload(null);
    setUploadError("");
    clearSelection();
  }, [clearSelection]);

  const loadCatalog = useCallback(async (append = false, next?: string | null) => {
    setCatalogState("loading");
    const params = new URLSearchParams({limit: "25"});
    if (query.trim()) params.set("query", query.trim());
    if (kind) params.set("viewer_kind", kind);
    if (append && next) params.set("cursor", next);
    try {
      const response = await fetch(`/api/files?${params}`, {cache: "no-store"});
      if (response.status === 401 || response.status === 403) {
        handleAccessLoss(response.status);
        return;
      }
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json() as CatalogPage;
      setFiles(current => append ? [...current, ...data.items] : data.items);
      setCursor(data.next_cursor ?? null);
      setCatalogState("ready");
    } catch {
      setCatalogState("error");
    }
  }, [handleAccessLoss, kind, query]);

  useEffect(() => {
    if (!identity) return;
    let active = true;
    const delay = setTimeout(() => void loadCatalog(false), 180);
    fetch("/api/files/upload-targets", {cache: "no-store"})
      .then(async response => {
        if (response.status === 401 || response.status === 403) {
          handleAccessLoss(response.status);
          throw new Error("access_revoked");
        }
        return response.ok ? await response.json() as {items: UploadTarget[]} : {items: []};
      })
      .then(data => { if (active) setTargets(data.items); })
      .catch(error => {
        if (active && (!(error instanceof Error) || error.message !== "access_revoked")) {
          setTargets([]);
        }
      });
    return () => {
      active = false;
      clearTimeout(delay);
    };
  }, [handleAccessLoss, identity, loadCatalog]);

  const updateLocator = useCallback((next: Locator) => {
    setLocator(next);
    const params = new URLSearchParams();
    if (selected) params.set("version", selected);
    const locatorParams = new URLSearchParams(locatorQuery(next));
    locatorParams.forEach((value, key) => params.set(key, value));
    history.replaceState({}, "", `/files?${params}`);
  }, [selected]);

  const selectVersion = useCallback((version: string | null, push = true) => {
    setSelected(version);
    setManifest(null);
    setViewerError("");
    setLocator({});
    const url = version ? `/files?version=${encodeURIComponent(version)}` : "/files";
    if (push) history.pushState({}, "", url);
    setCatalogOpen(false);
  }, []);

  useEffect(() => {
    if (!identity || !selected) return;
    let active = true;
    fetch(`/api/files/versions/${selected}/viewer-manifest`, {cache: "no-store"})
      .then(async response => {
        if ([401, 403, 404].includes(response.status)) {
          if (active) handleAccessLoss(response.status as 401 | 403 | 404);
          throw new Error("access_revoked");
        }
        if (!response.ok) throw new Error("manifest_unavailable");
        return parseManifest(await response.json());
      })
      .then(value => { if (active) setManifest(value); })
      .catch(error => {
        if (active && error instanceof Error && error.message !== "access_revoked") {
          setViewerError("Không thể mở bản xem an toàn.");
        }
      });
    return () => { active = false; };
  }, [handleAccessLoss, identity, selected]);

  useEffect(() => {
    if (!identity || !selected || !manifest) return;
    let running = false;
    const revalidate = async () => {
      if (running) return;
      running = true;
      revalidateAbort.current?.abort();
      const controller = new AbortController();
      revalidateAbort.current = controller;
      try {
        const response = await fetch(
          `/api/files/versions/${selected}/viewer-manifest`,
          {cache: "no-store", signal: controller.signal},
        );
        if ([401, 403, 404].includes(response.status)) {
          handleAccessLoss(response.status as 401 | 403 | 404);
          return;
        }
        if (response.ok) setManifest(parseManifest(await response.json()));
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setViewerError("Không thể xác minh lại quyền xem.");
        }
      } finally {
        running = false;
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") void revalidate();
    };
    addEventListener("focus", revalidate);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      revalidateAbort.current?.abort();
      removeEventListener("focus", revalidate);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [handleAccessLoss, identity, manifest, selected]);

  useEffect(() => () => {
    pollAbort.current?.abort();
    revalidateAbort.current?.abort();
  }, []);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setCatalogOpen(false);
        setRailOpen(false);
      }
    };
    addEventListener("keydown", close);
    return () => removeEventListener("keydown", close);
  }, []);

  async function pollUpload(statusUrl: string) {
    pollAbort.current?.abort();
    const controller = new AbortController();
    pollAbort.current = controller;
    let delay = 500;
    while (!controller.signal.aborted) {
      await new Promise(resolve => setTimeout(resolve, delay));
      const response = await fetch(statusUrl.replace("/api/v1/files/", "/api/files/"), {
        cache: "no-store", signal: controller.signal,
      });
      if (response.status === 401 || response.status === 403) {
        handleAccessLoss(response.status);
        return;
      }
      if (!response.ok) throw new Error("upload_status_unavailable");
      const current = await response.json() as UploadStatus;
      setUpload(current);
      if (["accepted", "rejected", "failed"].includes(current.state)) {
        if (current.state === "accepted" && current.version_id) {
          await loadCatalog(false);
          selectVersion(current.version_id);
        }
        return;
      }
      delay = Math.min(Math.round(delay * 1.5), 4000);
    }
  }

  async function startUpload(file: File, targetId: string) {
    setUploadError("");
    setUpload(null);
    try {
      const response = await fetch("/api/files/uploads", {
        method: "POST",
        headers: {
          "Content-Type": file.type || "application/octet-stream",
          "X-Parent-Resource-ID": targetId,
          "X-Logical-Name": file.name,
          "X-Original-Filename": file.name,
          ...(file.type ? {"X-Declared-MIME": file.type} : {}),
        },
        body: file,
      });
      if (response.status === 401 || response.status === 403) {
        handleAccessLoss(response.status);
        return;
      }
      const data = await response.json() as UploadStatus & {
        error?: {code?: string}; status_url?: string;
      };
      if (!response.ok || !data.status_url) throw new Error(data.error?.code ?? "upload_failed");
      setUpload({...data, progress: 0, retryable: false});
      await pollUpload(data.status_url);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "upload_failed");
    }
  }

  async function retryUpload() {
    if (!upload?.retryable) return;
    const response = await fetch(`/api/files/uploads/${upload.upload_id}/retry`, {method: "POST"});
    if (response.status === 401 || response.status === 403) {
      handleAccessLoss(response.status);
      return;
    }
    if (!response.ok) {
      setUploadError("retry_not_allowed");
      return;
    }
    await pollUpload(`/api/v1/files/uploads/${upload.upload_id}`);
  }

  const selectedFile = useMemo(
    () => files.find(file => file.version_id === selected) ?? null,
    [files, selected],
  );
  const railEntries = useMemo(
    () => manifest
      ? [manifestEvidence(manifest, selectedFile, locator, t("files.fileFallback"))]
      : [],
    [manifest, selectedFile, locator, t],
  );

  if (!authReady || !identity) {
    return <>
      <PageHeader eyebrow={t("files.eyebrow")} title={t("files.title")}/>
      <section className="placeholder-card">
        {!authReady && <p role="status">{t("shell.sessionChecking")}</p>}
        {authReady && <p className="lede">{t("files.gate.lede")}</p>}
        <div className="status" aria-live="polite">
          <div><span className={status.ok ? "dot ok" : "dot"}/><b>{status.status}</b></div>
        </div>
      </section>
    </>;
  }

  return <div className="files-workspace">
    <PageHeader eyebrow={t("files.eyebrow")} title={t("files.title")}
      actions={<div className="page-actions">
        <button className="files-catalog-toggle" type="button"
          onClick={() => {setRailOpen(false); setCatalogOpen(true);}}>
          {t("files.catalogButton")}
        </button>
        <button className="rail-sheet-toggle" type="button"
          onClick={() => {setCatalogOpen(false); setRailOpen(true);}}>
          {t("rail.toggle")}
        </button>
      </div>}/>
    <div className="files-layout">
      <aside className={`catalog ${catalogOpen ? "open" : ""}`}
        aria-label={t("files.catalogLabel")}>
        <div className="panel-heading"><h2>{t("files.catalogButton")}</h2>
          <button className="close-mobile" type="button" onClick={() => setCatalogOpen(false)}
            aria-label={t("files.closeCatalog")}>×</button></div>
        <label className="catalog-search">{t("files.search")}
          <input value={query} onChange={event => setQuery(event.target.value)}
            placeholder={t("files.searchPlaceholder")}/>
        </label>
        <div className="type-filters" aria-label={t("files.typeFilter")}>
          {TYPES.map(type => <button key={type.value || "all"} type="button"
            aria-pressed={kind === type.value} onClick={() => setKind(type.value)}>{type.label}</button>)}
        </div>
        <ul className="file-list">
          {files.map(file => <li key={file.version_id}>
            <button type="button" aria-current={selected === file.version_id ? "true" : undefined}
              onClick={() => selectVersion(file.version_id)}>
              <span className="file-kind">{file.viewer_kind}</span>
              <strong>{file.display_filename}</strong>
              <small>{readableBytes(file.byte_size)} · {file.classification}</small>
            </button>
          </li>)}
        </ul>
        {catalogState === "loading" && <p role="status">{t("files.loading")}</p>}
        {catalogState === "error" && <div role="alert">{t("files.error")}
          <button type="button" onClick={() => void loadCatalog(false)}>{t("surface.retry")}</button></div>}
        {catalogState === "ready" && files.length === 0 && <p>{t("files.empty")}</p>}
        {cursor && <button className="load-more" type="button"
          onClick={() => void loadCatalog(true, cursor)}>{t("files.loadMore")}</button>}
        <UploadPanel targets={targets} upload={upload} error={uploadError}
          onUpload={startUpload} onRetry={retryUpload}/>
      </aside>
      <section className="work-surface" aria-label={t("files.viewerLabel")}>
        <div className="locator-spine" aria-hidden><span>{
          locator.page ? `P${locator.page}` : locator.cell ?? locator.slide ?? (
            locator.t !== undefined ? `${(locator.t / 1000).toFixed(1)}s` : "—"
          )
        }</span></div>
        {!selected && <div className="viewer-empty"><p className="eyebrow">Safe rendition surface</p>
          <h2>Chọn một tệp để bắt đầu</h2><p>Chỉ các bản xem đã qua kiểm tra mới xuất hiện ở đây.</p></div>}
        {selected && !manifest && !viewerError && <p className="loading" role="status">Đang mở bản xem…</p>}
        {viewerError && <div className="partial" role="alert">{viewerError}</div>}
        {manifest && <FileViewer manifest={manifest} locator={locator}
          onLocator={updateLocator} onAccessLoss={handleAccessLoss}/>}
      </section>
      <EvidenceRail entries={railEntries} open={railOpen}
        onClose={() => setRailOpen(false)}
        note={manifest ? <div className="rail-note">
          <dl className="rail-facts">
            <div><dt>{t("files.format")}</dt>
              <dd>{manifest.viewer_kind} · {manifest.detected_mime}</dd></div>
            <div><dt>{t("files.preview")}</dt>
              <dd>{manifest.capabilities.preview
                ? t("files.previewAllowed") : t("files.previewUnavailable")}</dd></div>
            <div><dt>{t("files.download")}</dt>
              <dd>{manifest.capabilities.download_original
                ? t("files.downloadAllowed") : t("files.downloadDenied")}</dd></div>
            <div><dt>Checksum</dt><dd><code>{manifest.source_sha256.slice(0, 16)}…</code>
              <button type="button"
                onClick={() => void navigator.clipboard.writeText(manifest.source_sha256)}>
                {t("files.copyChecksum")}
              </button></dd></div>
            <div><dt>Locator</dt>
              <dd><code>rtr.locator.v1/{locatorQuery(locator) || "root"}</code>
                <button type="button"
                  onClick={() => void navigator.clipboard.writeText(location.href)}>
                  {t("files.copyLocatorLink")}
                </button></dd></div>
          </dl>
          {manifest.warnings.length > 0 && <div className="warnings">
            <strong>{t("files.qualityWarnings")}</strong>
            <ul>{manifest.warnings.map(item => <li key={item}>{item}</li>)}</ul></div>}
          {manifest.capabilities.download_original && <a className="download"
            href={`/api/files/versions/${manifest.version_id}/original`} download>
            {t("files.downloadOriginal")}
          </a>}
        </div> : null}/>
    </div>
    {(catalogOpen || railOpen) && <button className="scrim" type="button"
      aria-label="Đóng bảng điều khiển" onClick={() => {setCatalogOpen(false); setRailOpen(false);}}/>}
  </div>;
}

function UploadPanel({targets, upload, error, onUpload, onRetry}: {
  targets: UploadTarget[]; upload: UploadStatus | null; error: string;
  onUpload: (file: File, targetId: string) => Promise<void>; onRetry: () => Promise<void>;
}) {
  const {t} = useI18n();
  const [target, setTarget] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const effectiveTarget = target || targets[0]?.target_id || "";
  const accept = ".png,.jpg,.jpeg,.webp,.tif,.tiff,.pdf,.docx,.xlsx,.pptx,.mp4,.webm,.mp3,.m4a,.aac,.wav,.ogg,.opus";
  const submit = (file?: File) => {
    if (file && effectiveTarget) void onUpload(file, effectiveTarget);
  };
  return <section className="upload-panel" aria-label={t("files.upload.title")}
    onDragOver={event => event.preventDefault()}
    onDrop={event => {event.preventDefault(); submit(event.dataTransfer.files[0]);}}>
    <h2>{t("files.upload.title")}</h2>
    {targets.length ? <>
      <label>Đích lưu<select value={effectiveTarget} onChange={event => setTarget(event.target.value)}>
        {targets.map(item => <option key={item.target_id} value={item.target_id}>
          {item.label} · {item.classification}
        </option>)}
      </select></label>
      <input ref={input} className="sr-only" type="file" accept={accept}
        onChange={event => submit(event.target.files?.[0])}/>
      <button type="button" onClick={() => input.current?.click()}>{t("files.upload.pick")}</button>
      <small>Ảnh, PDF, DOCX, XLSX, PPTX, video và audio · tối đa theo chính sách máy chủ</small>
    </> : <p>Chưa có vị trí tải lên được cấp quyền.</p>}
    {upload && <div className="upload-progress" aria-live="polite">
      <progress max="100" value={upload.progress}/><span>{upload.state} · {upload.progress}%</span>
      {upload.retryable && <button type="button" onClick={() => void onRetry()}>{t("surface.retry")}</button>}
    </div>}
    {error && <p role="alert">Tải lên thất bại: {error}</p>}
  </section>;
}
