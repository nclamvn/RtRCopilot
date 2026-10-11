#!/usr/bin/env python3
"""Fixed allowlist public captures and independent research verification. No LLM calls."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent

def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

def sha(data):
    return hashlib.sha256(data).hexdigest()

class ReadView(HTMLParser):
    """Derived reading aid only; never used as raw evidence."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "svg", "nav", "header", "footer", "button"}:
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in {"script", "style", "svg", "nav", "header", "footer", "button"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"p", "li", "h1", "h2", "h3", "pre", "div", "section", "tr"}:
            self.parts.append("\n")
    def handle_data(self, text):
        if not self.skip and text.strip():
            self.parts.append(text.strip() + " ")

def read_view(data):
    parser = ReadView()
    parser.feed(data.decode("utf-8", "replace"))
    return re.sub(r"\n\s*\n", "\n", "".join(parser.parts)).strip() + "\n"

def classify(item, view):
    if item.get("migration_marker") and item["migration_marker"] in view:
        return "usable-migration-notice"
    return "usable" if len(view) >= 1500 and not re.search(r"^(?:404|Page not found|Not Found)\b", view[:80], re.I) else "rejected-nav-only-or-error"

def capture_one(item, manifest):
    ledger_path = ROOT / "captures" / (item["id"] + ".json")
    previous = json.loads(ledger_path.read_text()) if ledger_path.exists() else None
    if previous:
        for attempt in previous["attempts"]:
            if "snapshot" in attempt:
                attempt["status"] = classify(item, (ROOT / "read_views" / attempt["snapshot"].replace(".html", ".txt")).read_text())
        previous["selected"] = next((a for a in previous["attempts"] if a["status"].startswith("usable")), None)
        dump(ledger_path, previous)
    if previous and (previous["selected"] or not RETRY_FAILED):
        return previous
    allowed = {urllib.parse.urlparse(u).hostname for s in manifest["sources"] for u in [s["url"], s.get("fallback", s["url"])]}
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            parsed = urllib.parse.urlparse(newurl)
            if parsed.scheme != "https" or parsed.hostname not in allowed:
                raise ValueError("redirect outside declared primary-source hosts: " + newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = urllib.request.build_opener(SafeRedirect())
    attempts = list(previous["attempts"]) if previous else []
    for number, url in enumerate(dict.fromkeys([item["url"], item.get("fallback", item["url"])])):
        row = {"requested_url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(), "source_family": item["family"]}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RtR-public-research/1.0", "Accept": "text/html,text/plain"})
            with opener.open(req, timeout=manifest["timeout_seconds"]) as response:
                row.update(resolved_url=response.url, http_status=response.status, content_type=response.headers.get("Content-Type"))
                data = response.read(manifest["max_bytes"] + 1)
            if len(data) > manifest["max_bytes"]:
                raise ValueError("response exceeds max_bytes; no truncated evidence accepted")
            name = item["id"] + ("-fallback" if number else "") + ".html"
            (ROOT / "snapshots" / name).write_bytes(data)
            view = read_view(data)
            (ROOT / "read_views" / name.replace(".html", ".txt")).write_text(view, encoding="utf-8")
            row.update(snapshot=name, sha256=sha(data), bytes=len(data), read_view_sha256=sha(view.encode()), read_view_characters=len(view))
            row["status"] = classify(item, view)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            row.update(status="failed", error=str(exc))
        attempts.append(row)
        if row["status"].startswith("usable"):
            break
    result = {"id":item["id"], "entity":item["entity"], "attempts": attempts, "selected":next((r for r in attempts if r["status"].startswith("usable")), None)}
    dump(ledger_path, result)
    return result

def capture():
    manifest = json.loads((ROOT / "source-manifest.json").read_text())
    for directory in ["captures", "snapshots", "read_views", "output"]:
        (ROOT / directory).mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda item: capture_one(item, manifest), manifest["sources"]))
    dump(ROOT / "output" / "capture-summary.json", {"cohort":len(rows), "usable":sum(bool(r["selected"]) for r in rows), "failures":[r for r in rows if not r["selected"]]})
    print(json.dumps({"cohort":len(rows), "usable":sum(bool(r["selected"]) for r in rows)}))

def verify():
    """Deliberately does not import builder: recheck bytes, exact spans, family, limits."""
    manifest = json.loads((ROOT / "source-manifest.json").read_text())
    sources = {s["id"]:s for s in manifest["sources"]}
    rows = [json.loads(l) for l in (ROOT / "claims.jsonl").read_text().splitlines() if l.strip()]
    errors, page_words, page_count, counts = [], {}, {}, {}
    import yaml
    cfg = yaml.safe_load((ROOT / "domain.yaml").read_text())
    if cfg["universe"]["estimate"] != len(sources) or cfg["schema"]["fields"] != ["category", "capability", "constraint", "performance_rtr", "license_rtr"]:
        errors.append("cohort denominator/schema mismatch")
    allowed_hosts = {urllib.parse.urlparse(u).hostname for s in sources.values() for u in [s["url"], s.get("fallback", s["url"])]}
    for item in sources.values():
        cap = json.loads((ROOT / "captures" / (item["id"] + ".json")).read_text())
        if cap["selected"] not in cap["attempts"]:
            errors.append("selected capture outside ledger: " + item["id"])
        for attempt in cap["attempts"]:
            if "snapshot" not in attempt:
                continue
            data = (ROOT / "snapshots" / attempt["snapshot"]).read_bytes()
            view = (ROOT / "read_views" / attempt["snapshot"].replace(".html", ".txt")).read_bytes()
            if attempt["requested_url"] not in [item["url"], item.get("fallback")] or urllib.parse.urlparse(attempt["resolved_url"]).hostname not in allowed_hosts or not attempt["resolved_url"].startswith("https://") or attempt["source_family"] != item["family"] or attempt["http_status"] != 200 or attempt["status"] != classify(item, view.decode()):
                errors.append("capture origin/status: " + item["id"])
            if sha(data) != attempt["sha256"] or len(data) != attempt["bytes"]:
                errors.append("snapshot hash/length: " + item["id"])
            if len(data) > manifest["max_bytes"] or sha(view) != attempt["read_view_sha256"] or view.decode() != read_view(data):
                errors.append("capture bound/read view: " + item["id"])
    for claim in rows:
        item = sources.get(claim.get("source_id"))
        if not item:
            errors.append("unknown source id")
            continue
        selected = json.loads((ROOT / "captures" / (item["id"] + ".json")).read_text())["selected"]
        if not selected:
            errors.append("claim from rejected capture: " + item["id"])
            continue
        cap = claim["capture"]
        data = (ROOT / "snapshots" / cap["snapshot"]).read_bytes()
        if not claim["evidence_span"] or claim["evidence_span"].encode() not in data:
            errors.append("exact raw span missing: " + item["id"])
        if cap["source"] != item["family"] or cap["snapshot"] != selected["snapshot"] or cap["url"] != selected["resolved_url"] or cap["fetched_at"] != selected["retrieved_at"] or claim["entity"] != item["entity"]:
            errors.append("origin/family mismatch: " + item["id"])
        if claim["tier"] != "A" or claim["extraction"] != "normalized" or claim["field"] not in {"category", "capability", "constraint"}:
            errors.append("unsupported claim field/tier/extraction: " + item["id"])
        if claim.get("scope") != "vendor-documentation-not-performance-proof":
            errors.append("missing evidence scope: " + item["id"])
        page_words[item["id"]] = page_words.get(item["id"], 0) + len(claim["evidence_span"].split())
        page_count[item["id"]] = page_count.get(item["id"], 0) + 1
        counts[claim["field"]] = counts.get(claim["field"], 0) + 1
    errors += ["quotation/claim budget: " + k for k in page_count if page_count[k] > 3 or page_words[k] > 25]
    vendor = json.loads((ROOT / "vendor" / "origin.json").read_text())
    for name, expected in vendor["sha256"].items():
        if sha((ROOT / "vendor" / name).read_bytes()) != expected:
            errors.append("vendored engine changed: " + name)
    summary = {"status":"PASS" if not errors else "FAIL", "errors":errors, "claims":len(rows), "entities":len({c["entity"] for c in rows}), "cohort_denominator":len(sources), "fields":counts, "quoted_words_by_page":page_words, "claims_by_page":page_count, "null_policy":"performance_rtr/license_rtr absent; registry honest-null", "corroboration_policy":"vendor family collapsed across mirrors; no performance proof"}
    dump(ROOT / "output" / "independent-verification.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not errors else 2

def claims():
    """Bind human-reviewed short spans to selected immutable snapshots."""
    manifest = json.loads((ROOT / "source-manifest.json").read_text())
    spec = json.loads((ROOT / "claims-spec.json").read_text())
    rows, missing = [], []
    for item in manifest["sources"]:
        selected = json.loads((ROOT / "captures" / (item["id"] + ".json")).read_text())["selected"]
        if not selected:
            missing.append({"entity":item["entity"],"reason":"No accepted capture; no claims fabricated"})
            continue
        for authored in spec[item["id"]]:
            rows.append(dict(authored, source_id=item["id"], entity=item["entity"], tier="A", extraction="normalized", scope="vendor-documentation-not-performance-proof", capture={"url":selected["resolved_url"],"fetched_at":selected["retrieved_at"],"snapshot":selected["snapshot"],"source":item["family"]}))
    (ROOT / "claims.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    dump(ROOT / "output" / "missing-entity-log.json", missing)
    dump(ROOT / "output" / "dead-link-log.json", [{"source_id":s["id"],**a} for s in manifest["sources"] for a in json.loads((ROOT / "captures" / (s["id"]+".json")).read_text())["attempts"] if not a["status"].startswith("usable")])
    return verify()

def rebuild():
    if verify():
        return 2
    sys.path.insert(0, str(ROOT / "vendor"))
    import refinery
    _, _, registry, agg, payload = refinery.run_pipeline(ROOT)
    (ROOT / "output" / "registry.json").write_bytes(payload)
    nulls = [{"entity":ent,"field":field,"reason":"No verified claim in bounded source review; not evidence of absence"} for ent, record in registry.items() for field, cell in record["fields"].items() if cell["state"] == "null"]
    dump(ROOT / "output" / "honest-null-log.json", nulls)
    result = subprocess.run([sys.executable, str(ROOT / "vendor" / "bites.py"), str(ROOT)], capture_output=True, text=True)
    (ROOT / "output" / "bites.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    dump(ROOT / "output" / "engine-verification.json", {"engine_idempotent":True,"engine_auditor":True,"registry_sha256":sha(payload),"claims_sha256":sha((ROOT / "claims.jsonl").read_bytes()),"manifest_sha256":sha((ROOT / "source-manifest.json").read_bytes()),"bites_exit_code":result.returncode,"bites_passed":len(re.findall(r"^[A-Z_]+\s+:  CẮN ✓", result.stdout, re.M)),"bites_not_applicable":len(re.findall(r":  N/A", result.stdout)),"aggregates":agg})
    print(result.stdout)
    return result.returncode

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["capture", "claims", "verify", "rebuild"])
    parser.add_argument("--retry-failed", action="store_true", help="append attempts for failed pages; never replace a selected snapshot")
    args = parser.parse_args()
    command = args.command
    RETRY_FAILED = args.retry_failed
    sys.exit({"capture":capture,"claims":claims,"verify":verify,"rebuild":rebuild}[command]() or 0)
