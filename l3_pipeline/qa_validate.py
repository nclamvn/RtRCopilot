#!/usr/bin/env python3
"""QA validator for TIP-1..4 candidate cards. Contractor reverse-check.
Checks schema conformance + the 6 hard rules. Non-destructive (read-only)."""
import yaml, re, os, sys

BASE = "/Users/os/RtR/KnowledgeBase/RtR_Copilot/l3_pipeline/candidates"
FILES = {
    1: "tip1_website_xpo26.yaml",
    2: "tip2_knowledgebase.yaml",
    3: "tip3_news_output_ceo.yaml",
    4: "tip4_systems.yaml",
}
REQUIRED = ["id","content","domain","source_path","evidence_span","extraction",
            "tier_proposed","owner_hint","effective_date","kernel_check","kernel_ref"]
DOMAINS = {"product","process","company","legal","system","brand","event"}
EXTRACTION = {"verbatim","normalized","inferred"}
TIERS = {"L2","L3","L4"}
KCHECK = {"new","duplicate","conflict","legacy","unsure"}

VALID_KERNEL = set(re.findall(r'\b(?:HC|SC|OC|EC|PC|MC)-\d{3}\b',
                   open("/Users/os/RtR/kernel/registry/capabilities.yaml").read()))
VALID_KERNEL |= {"SPEC-SYNC-02"}
# kernel/_dist doc names are also valid kernel_ref targets (doctrine/legal/positioning/changelog)
DIST_DOCS = set()
for root,_,fs in os.walk("/Users/os/RtR/kernel/_dist"):
    for fn in fs:
        DIST_DOCS.add(os.path.splitext(fn)[0])

LEGACY_PAT = re.compile(r'\b(15\s?kg|15 kilogram|33\s?lbs?|33\s?pound|1-4-15)\b', re.I)
SENSITIVE_PAT = re.compile(r'\b(price|pricing|giá bán|giá vốn|quote|báo giá|deal reg|USD\b|\$\d|VNĐ|VND\b)', re.I)

# Hard errors (card would be rejected at VERIFY), and soft warnings (review).
errors, warns = [], []
all_ids = {}
counts = {"cards":0}
per_file = {}

def add_err(cid, msg): errors.append(f"{cid}: {msg}")
def add_warn(cid, msg): warns.append(f"{cid}: {msg}")

def path_exists(sp):
    if not sp: return False, ""
    p = sp.strip().strip('"').strip("'")  # keep spaces — paths legitimately contain them
    # map stale sandbox prefix to real base
    p = p.replace("/sessions/intelligent-affectionate-planck/mnt/", "/Users/os/RtR/")
    p = p.replace("/sessions/intelligent-affectionate-planck/mnt", "/Users/os/RtR")
    return os.path.exists(p), p

for tip, fname in FILES.items():
    fpath = os.path.join(BASE, fname)
    with open(fpath) as fh:
        try:
            doc = yaml.safe_load(fh)
        except Exception as e:
            add_err(fname, f"YAML PARSE FAIL: {e}"); per_file[tip]=0; continue
    cards = doc.get("candidates") if isinstance(doc, dict) else None
    if cards is None:
        add_err(fname, "missing top-level `candidates:` list"); per_file[tip]=0; continue
    per_file[tip] = len(cards)
    for c in cards:
        counts["cards"] += 1
        cid = c.get("id","<no-id>")
        # id format + tip match + uniqueness
        m = re.fullmatch(r'CAND\.(\d)\.(\d{3})', str(cid))
        if not m:
            add_err(cid, "id not matching CAND.N.NNN")
        else:
            if int(m.group(1)) != tip:
                add_err(cid, f"id TIP number {m.group(1)} != file TIP {tip}")
        if cid in all_ids:
            add_err(cid, f"DUPLICATE id (also in {all_ids[cid]})")
        all_ids[cid] = fname
        # required fields present
        for k in REQUIRED:
            if k not in c:
                add_err(cid, f"missing field `{k}`")
        # enum checks
        if c.get("domain") not in DOMAINS: add_err(cid, f"bad domain: {c.get('domain')}")
        if c.get("extraction") not in EXTRACTION: add_err(cid, f"bad extraction: {c.get('extraction')}")
        if c.get("tier_proposed") not in TIERS: add_err(cid, f"bad tier: {c.get('tier_proposed')}")
        kc = c.get("kernel_check")
        if kc not in KCHECK: add_err(cid, f"bad kernel_check: {kc}")
        # rule 3: evidence + source_path non-empty
        ev = (c.get("evidence_span") or "")
        if not str(ev).strip(): add_err(cid, "empty evidence_span (rule 3)")
        sp = (c.get("source_path") or "")
        if not str(sp).strip(): add_err(cid, "empty source_path")
        else:
            exists, realp = path_exists(str(sp))
            if str(sp).startswith("/sessions/"):
                add_warn(cid, f"source_path uses stale sandbox prefix: {sp}")
            if not exists:
                add_warn(cid, f"source_path not found on disk: {sp}")
        # rule 1: duplicate/conflict need kernel_ref
        kref = c.get("kernel_ref")
        if kc in ("duplicate","conflict"):
            if not kref or str(kref).strip().lower() in ("null","none",""):
                add_err(cid, f"kernel_check={kc} but kernel_ref empty (rule 1)")
            else:
                toks = set(re.findall(r'\b(?:HC|SC|OC|EC|PC|MC)-\d{3}\b', str(kref)))
                cites_dist = any(d in str(kref) for d in DIST_DOCS)
                recognized = (toks & VALID_KERNEL) or "SPEC-SYNC" in str(kref) \
                    or "SIG." in str(kref) or cites_dist or re.search(r'\bD\d\b', str(kref))
                if not recognized:
                    add_warn(cid, f"kernel_ref has no recognized kernel id/doc: {kref}")
                else:
                    bad = toks - VALID_KERNEL
                    if bad: add_warn(cid, f"kernel_ref cites unknown capability id(s): {bad}")
        else:
            if kref and str(kref).strip().lower() not in ("null","none",""):
                add_warn(cid, f"kernel_check={kc} but kernel_ref set ({kref}) — expected null")
        # rule 2: legacy 15kg/33lb
        blob = f"{c.get('content','')} {ev}"
        if LEGACY_PAT.search(blob):
            if kc != "legacy":
                # allow explicit historical/DCMA-context notes
                note = str(c.get("note","")).lower()
                if not any(w in note for w in ("legacy","lịch sử","historical","dcma","theoretical")):
                    add_err(cid, f"mentions 15kg/33lb/1-4-15 but kernel_check={kc} (rule 2 → legacy)")
                else:
                    add_warn(cid, f"mentions 15kg/33lb but kc={kc}; note claims historical context — confirm")
        # effective_date format
        edate = c.get("effective_date")
        if edate not in (None, "null") and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(edate)):
            add_warn(cid, f"effective_date not YYYY-MM-DD or null: {edate}")
        # rule 5: sensitive → L2 (soft)
        if SENSITIVE_PAT.search(blob) and c.get("tier_proposed") == "L3":
            add_warn(cid, f"content looks sensitive (pricing/deal) but tier=L3 (rule 5?) :: {SENSITIVE_PAT.search(blob).group(0)}")

print("=== PER-FILE CARD COUNT ===")
for t in sorted(per_file): print(f"  TIP-{t}: {per_file[t]} cards")
print(f"  TOTAL: {counts['cards']} cards, {len(all_ids)} unique ids")
print(f"\n=== HARD ERRORS (would fail VERIFY): {len(errors)} ===")
for e in errors: print("  ✗", e)
print(f"\n=== SOFT WARNINGS (review): {len(warns)} ===")
for w in warns: print("  ⚠", w)
print(f"\nRESULT: {'PASS — no hard errors' if not errors else 'FAIL — ' + str(len(errors)) + ' hard errors'}")
