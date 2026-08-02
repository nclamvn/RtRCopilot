#!/usr/bin/env python3
"""TIP-013B LOCAL demo · capture the real Q&A evidence set to JSON.

Drives the REAL dev-OIDC login flow against the running api and asks real RtR
questions, dumping the full responses (answer text, citations, confidence
caveat) to ``/tmp/rtr-demo/qa_capture.json``.  Every answer is a genuine,
grounded response from the activated real-kernel facts — nothing is mocked.
"""
from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx

BASE = "http://127.0.0.1:8000"
OUT = "/tmp/rtr-demo/qa_capture.json"


def login(client: httpx.Client) -> dict:
    r = client.get(f"{BASE}/auth/login", follow_redirects=False)
    q1 = urlparse(r.headers["location"]).query
    r = client.get(
        f"{BASE}/auth/dev/authorize?{q1}&email=staff@rtrobotics.com&sub=dev-staff",
        follow_redirects=False,
    )
    q2 = urlparse(r.headers["location"]).query
    client.get(f"{BASE}/auth/callback?{q2}", follow_redirects=False)
    return client.get(f"{BASE}/auth/me").json()


def ask(
    client: httpx.Client,
    label: str,
    question: str,
    source_key: str | None = None,
    require_verified: bool = False,
) -> dict:
    body: dict = {"question": question, "require_verified": require_verified}
    if source_key:
        body["filters"] = {"source_key": source_key}
    r = client.post(f"{BASE}/api/v1/ask", json=body)
    return {
        "label": label,
        "question": question,
        "source_key_filter": source_key,
        "http_status": r.status_code,
        "response": r.json(),
    }


def search(client: httpx.Client, label: str, query: str) -> dict:
    r = client.post(f"{BASE}/api/v1/search", json={"query": query})
    hits = [
        {
            "record_key": h["citation"]["record_key"],
            "provenance_level": h["citation"]["provenance_level"],
            "verification_state": h["citation"]["verification_state"],
            "fusion_score": h["fusion_score"],
            "snippet": h["snippet"][:160],
        }
        for h in r.json().get("results", [])[:5]
    ]
    return {"label": label, "query": query, "hits": hits}


def main() -> int:
    with httpx.Client(timeout=30) as client:
        me = login(client)
        asks = [
            ask(client, "HERA max payload (strict, 15 kg)",
                "Maximum payload capacity", "rtr.specs"),
            ask(client, "HERA signature 1-4-14 payload bays (soft)",
                "Payload đồng thời", "rtr.specs"),
            ask(client, "HERA MTOW per Capability Matrix HC-001 (soft)",
                "HERA MTOW", "rtr.specs"),
            ask(client, "VEGA US list price (soft)",
                "VEGA giá bao nhiêu", "rtr.prices"),
            ask(client, "HERA motors (strict only -> NO caveat)",
                "motors", "rtr.specs"),
            ask(client, "No-evidence question -> honest-null",
                "Ai là tổng giám đốc điều hành của công ty"),
            ask(client, "VEGA tải trọng via offline provider (honest-null)",
                "VEGA tải trọng tối đa"),
        ]
        searches = [
            search(client, "VEGA payload fact is live (L3R.1.010)",
                   "VEGA tải trọng payload"),
        ]
    out = {"subject": me, "asks": asks, "searches": searches}
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=2)
    for item in asks:
        rsp = item["response"]
        state = rsp["state"]
        caveat = rsp.get("confidence_caveat")
        ncit = len(rsp.get("citations", []))
        print(f"[{item['label']}] -> {state} caveat={caveat} ncit={ncit}")
    print(f"captured -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
