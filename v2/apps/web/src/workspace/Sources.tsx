"use client";

import {useEffect, useRef, useState, type FormEvent} from "react";
import {api, apiRoot} from "./api";
import {type ResearchSource, type SourceFile, type SourcePage} from "./contracts";

export function SourcePreview({file}: {file: SourceFile}) {
  const [page, setPage] = useState<SourcePage | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    let disposed = false;
    void api<SourcePage>(`/files/${file.id}?offset=${offset}&limit=16000`).then(result => {if (!disposed) {setPage(result); setError("");}}).catch(cause => {if (!disposed) setError(cause.message);});
    return () => {disposed = true;};
  }, [file.id, offset]);
  return <section className="aw-source-preview" aria-label="Source preview"><h3>{file.filename}</h3><p className="aw-muted">{file.bytes.toLocaleString()} original bytes · extracted text preview</p>
    {file.provenance && Object.keys(file.provenance).length > 0 && <details><summary>Source provenance</summary><dl>{Object.entries(file.provenance).map(([name, value]) => <div key={name}><dt>{name.replaceAll("_", " ")}</dt><dd>{String(value)}</dd></div>)}</dl>{file.sha256 && !file.provenance.sha256 && <p className="aw-checksum">SHA-256 {file.sha256}</p>}</details>}
    {file.warnings?.map((warning, i) => <p key={i} className="aw-draft-note">{warning}</p>)}
    {error && <p role="alert" className="aw-inline-error">{error}</p>}
    {page ? <><pre className="aw-source-text">{page.content}</pre><div className="aw-page-controls"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 16000))}>Previous page</button><span>{offset + 1}–{Math.min(offset + page.content.length, page.total_characters)} of {page.total_characters}</span><button disabled={!page.has_more} onClick={() => setOffset(page.next_offset ?? offset + page.content.length)}>Next page</button></div></> : <p role="status">Loading source…</p>}
    <a className="aw-original-download" href={`${apiRoot}/files/${file.id}/download`} download>Download original</a>
  </section>;
}

export function LocalResearch({workspaceId, onImported}: {workspaceId: string; onImported: (file: SourceFile) => Promise<void>}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ResearchSource[] | null>(null);
  const [reading, setReading] = useState<{id: string; title: string; content: string} | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  async function search(event: FormEvent) {
    event.preventDefault(); if (!query.trim() || lock.current) return;
    lock.current = true; setBusy(true); setError(""); setReading(null);
    try {const result = await api<{fixture: true; results: ResearchSource[]}>(`/workspaces/${workspaceId}/research/search`, {query: query.trim()}); setResults(result.results);}
    catch (cause) {setError((cause as Error).message);}
    finally {lock.current = false; setBusy(false);}
  }
  async function read(id: string) {
    setError("");
    try {const result = await api<{source: {id: string; title: string; content: string}}>(`/workspaces/${workspaceId}/research/read`, {source_id: id}); setReading(result.source);}
    catch (cause) {setError((cause as Error).message);}
  }
  async function importSource(id: string) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {const file = await api<SourceFile>(`/workspaces/${workspaceId}/research/import`, {source_id: id}); await onImported(file);}
    catch (cause) {setError((cause as Error).message);}
    finally {lock.current = false; setBusy(false);}
  }
  return <section className="aw-research" aria-label="Local research"><p className="aw-draft-note">Offline fixture library only. No live web search, URL fetch, or network research is enabled.</p><form onSubmit={search}><label htmlFor="aw-research-query">Search local fixture sources</label><div><input id="aw-research-query" maxLength={200} value={query} onChange={event => setQuery(event.target.value)} placeholder="e.g. harbor or water"/><button disabled={busy || !query.trim()}>Search fixtures</button></div></form>{error && <p role="alert" className="aw-inline-error">{error}</p>}{results && <p className="aw-muted" role="status">{results.length} local fixture result(s)</p>}<ul className="aw-research-results">{results?.map(source => <li key={source.id}><span className="aw-fixture-badge">Offline fixture</span><h3>{source.title}</h3><p>{source.snippet}</p><p className="aw-research-url">{source.url}</p><small>Snapshot: {source.as_of}</small><div><button disabled={busy} onClick={() => void read(source.id)}>Read snapshot</button><button disabled={busy} onClick={() => void importSource(source.id)}>Import snapshot</button></div>{reading?.id === source.id && <pre className="aw-source-text">{reading.content}</pre>}</li>)}</ul></section>;
}
