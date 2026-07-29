#!/usr/bin/env python3
"""RtR Copilot · pilot server Phase 1 · hai chế độ LIVE (Claude API) và MOCK (retrieval máy).

Zero dependency ngoài Python 3 chuẩn. Chạy:

    export ANTHROPIC_API_KEY=sk-ant-...        # có key = chế độ LIVE (AI trả lời)
    export COPILOT_PASSCODE=matkhau-noi-bo     # bắt buộc nếu muốn mở cho LAN
    python3 copilot_server.py

KHÔNG có key server vẫn chạy đủ UI ở chế độ MOCK: trả lời bằng máy tra cứu SOT
(top record khớp nhất + citation, dán nhãn MOCK rõ ràng). Toàn bộ UI/UX, tra cứu,
GAP log, audit log test được không cần API. Cắm key vào là LIVE, không sửa gì.

Kiến trúc: GOI_L3.yaml (gói từ kernel) là nguồn duy nhất (NT-1). GAP tự log
gap_log.jsonl · hỏi đáp log qa_log.jsonl.
"""
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("COPILOT_PORT", "8787"))
MODEL = os.environ.get("COPILOT_MODEL", "claude-sonnet-5")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PASSCODE = os.environ.get("COPILOT_PASSCODE", "")
MODE = "LIVE" if API_KEY else "MOCK"

# ---------- Nạp gói (parser YAML tối giản cho đúng format l3_export · zero-dep) ----------
def find(fname):
    for p in [HERE / fname, HERE.parent / "l3_pipeline" / fname]:
        if p.exists():
            return p
    sys.exit(f"Không tìm thấy {fname} · đặt cạnh script hoặc trong ../l3_pipeline/")

# ---------- Chọn gói · staff (L3, mặc định) hay leader (L3 + L2 giá + L4 văn phong) ----------
PACK = os.environ.get("COPILOT_PACK", "staff").lower()
if PACK not in ("staff", "leader"):
    sys.exit(f"COPILOT_PACK phải là 'staff' hoặc 'leader', nhận '{PACK}'")

# RÀNG BUỘC CỨNG (allowlist RB.1-RB.3) · khoá bằng code, không bằng quy trình.
# Gói leader chứa giá bán và chính sách chiết khấu. Chế độ MOCK là máy tra cứu
# thuần: gặp từ khoá khớp là trả NGUYÊN VĂN record, không có lớp phán đoán nào.
# Chạy gói leader ở MOCK = nhả thẳng bảng giá ra màn hình.
if PACK == "leader":
    if MODE != "LIVE":
        sys.exit("TỪ CHỐI KHỞI ĐỘNG · gói leader chứa thông tin hạn chế, chỉ chạy được ở chế độ LIVE.\n"
                 "Chế độ MOCK trả nguyên văn record khớp từ khoá, không có lớp phán đoán.\n"
                 "Cần: export ANTHROPIC_API_KEY=... rồi chạy lại. (ràng buộc RB.1)")
    if not PASSCODE:
        sys.exit("TỪ CHỐI KHỞI ĐỘNG · gói leader bắt buộc có passcode riêng.\n"
                 "Cần: export COPILOT_PASSCODE=<mã riêng cho nhóm lãnh đạo> · KHÁC mã gói nhân viên. (RB.2, RB.3)")

GOI_PATH = find("GOI_LEADER.yaml" if PACK == "leader" else "GOI_L3.yaml")
GOI_TEXT = GOI_PATH.read_text(encoding="utf-8")

def _clean(v):
    """Bỏ quote YAML bao ngoài + unescape '' của single-quote scalar."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    elif v.startswith("'") or v.startswith('"'):
        v = v[1:]
    elif v.endswith("'") or v.endswith('"'):
        v = v[:-1]
    return v.replace("''", "'").strip()

def parse_records(text):
    """Parse list records từ GOI_L3.yaml (format do l3_export.py sinh · ổn định).
    Multiline scalar: MỌI dòng thụt >=4 space nối vào key gần nhất (kể cả value cùng dòng)."""
    recs = []
    cur = None
    last_key = None
    in_records = False
    for line in text.splitlines():
        if line.startswith("records:"):
            in_records = True
            continue
        if not in_records:
            continue
        m = re.match(r"^- record: (.+)$", line)
        if m:
            if cur:
                recs.append(cur)
            cur = {"record": _clean(m.group(1)), "content": ""}
            last_key = None
            continue
        if cur is None:
            continue
        m = re.match(r"^  (\w+): ?(.*)$", line)
        if m:
            last_key = m.group(1)
            v = m.group(2).strip()
            cur[last_key] = "" if v in (">", ">-", "|", "|-") else v
            continue
        m = re.match(r"^ {4,}(.*)$", line)
        if m and last_key:
            cur[last_key] = (cur[last_key] + " " + m.group(1).strip()).strip()
    if cur:
        recs.append(cur)
    for r in recs:
        for k in list(r):
            if isinstance(r[k], str):
                r[k] = _clean(r[k])
    return recs

RECORDS = parse_records(GOI_TEXT)
BY_ID = {r["record"]: r for r in RECORDS}

_tip7 = find("TIP7_SYSTEM_PROMPT_ClaudeProject.md").read_text(encoding="utf-8")
SYSTEM = _tip7.split("---", 1)[-1].strip() + "\n\n## GÓI TRI THỨC L3 (nguồn duy nhất · NT-1)\n\n" + GOI_TEXT

GAP_LOG = HERE / "gap_log.jsonl"
QA_LOG = HERE / "qa_log.jsonl"
ISSUE_LOG = HERE / "issue_log.jsonl"   # ca người dùng báo bot trả lời sai

# ---------- Người dùng · ba tầng nhận diện, ưu tiên từ chặt tới lỏng ----------
# 1. TÀI KHOẢN (auth.py) · người tự đăng ký bằng email công ty, admin phân vai.
#    Đây là đường chính từ 29/07/2026. Hễ đã có một tài khoản hoạt động là
#    server dùng đường này và BỎ QUA hai đường dưới.
# 2. users.yaml · mã riêng từng người, Lâm gõ tay. Đường lùi cho pilot cũ.
# 3. COPILOT_PASSCODE · mã chung. Không đếm được người thực, chỉ để chạy thử.
try:
    import auth
except Exception as _e:                       # pragma: no cover
    auth = None
    print(f"CHÚ Ý: không nạp được auth.py ({_e}) · quay về mã chung")

USERS = {}
_ufile = HERE / "users.yaml"
if _ufile.exists():
    try:
        import yaml as _yaml
        for u in (_yaml.safe_load(_ufile.read_text(encoding="utf-8")) or {}).get("users", []):
            if u.get("ma"):
                USERS[str(u["ma"]).strip()] = {"ten": u.get("ten", "?"),
                                               "phong": u.get("phong", ""),
                                               "quyen": u.get("quyen", "staff")}
    except Exception as _e:
        print(f"CHÚ Ý: đọc users.yaml lỗi ({_e}) · quay về dùng passcode chung")

# Từ vựng vai CŨ (staff/leader) sang vai MỚI (nhanvien/lanhdao/quantri). Giữ bảng
# dịch thay vì sửa users.yaml để hai đường cũ chạy tiếp không cần đụng file.
_VAI_CU = {"staff": "nhanvien", "leader": "lanhdao", "admin": "quantri"}


def _chuan_vai(u):
    if not u:
        return None
    q = u.get("quyen", "")
    u["quyen"] = _VAI_CU.get(q, q if q in ("nhanvien", "lanhdao", "quantri") else "nhanvien")
    return u


def dung_tai_khoan():
    return bool(auth and auth.co_tai_khoan())


def who(handler):
    """Nhận diện người gọi. Trả về (ok, user|None, loi).

    user luôn có `quyen` thuộc nhanvien|lanhdao|quantri sau khi qua đây, nên phần
    còn lại của server chỉ cần biết một từ vựng vai duy nhất.
    """
    tok = (handler.headers.get("x-token", "") or "").strip()
    code = (handler.headers.get("x-passcode", "") or "").strip()

    if dung_tai_khoan():
        acc, err = auth.doc_token(tok)
        if not acc:
            return False, None, err or "Chưa đăng nhập"
        u = {"ten": acc["ten"], "email": acc["email"], "quyen": acc["quyen"], "phong": ""}
        if PACK == "leader" and not auth.duoc(acc, "doc_han_che"):
            # Gói lãnh đạo chứa giá VỐN linh kiện + tên nhà cung cấp. Tài khoản vai
            # nhân viên KHÔNG vào được, kể cả khi đăng nhập hợp lệ ở gói chung.
            return False, u, "Tài khoản vai nhân viên không vào được gói lãnh đạo"
        return True, u, ""

    if USERS:
        u = _chuan_vai(dict(USERS.get(code) or {})) if code in USERS else None
        if not u:
            return False, None, "Mã đăng nhập không đúng · hỏi anh Lâm"
        if PACK == "leader" and u["quyen"] == "nhanvien":
            return False, u, "Tài khoản này không có quyền vào gói lãnh đạo"
        return True, u, ""

    if PASSCODE and code != PASSCODE:
        return False, None, "Sai mã nội bộ"
    # Chế độ mã chung: không biết người gọi là ai, nên cấp vai theo GÓI đang phục vụ.
    # Gói lãnh đạo đã bị chặn ở tầng khởi động nếu không có passcode (RB.2).
    return True, {"ten": "không rõ", "email": "", "phong": "",
                  "quyen": "lanhdao" if PACK == "leader" else "nhanvien"}, ""


BAC_VAI = {"nhanvien": 1, "lanhdao": 2, "quantri": 3}
BANG_QUYEN = (auth.QUYEN if auth else {
    "hoi": "nhanvien", "tra_cuu": "nhanvien", "bao_sai": "nhanvien",
    "de_xuat_fact": "nhanvien", "sinh_tai_lieu": "nhanvien",
    "doc_han_che": "lanhdao", "sinh_cong_van": "lanhdao", "duyet_bao_sai": "lanhdao",
    "xem_thong_ke": "lanhdao", "xem_ten_nguoi_hoi": "quantri",
    "quan_tri_nguoi_dung": "quantri", "ghi_kernel": "quantri"})


def duoc_lam(user, hanh_dong):
    """Câu hỏi quyền DUY NHẤT của cả server. Hành động chưa khai = cấm (fail-closed)."""
    can = BANG_QUYEN.get(hanh_dong)
    if can is None or not user:
        return False
    return BAC_VAI.get(user.get("quyen", ""), 0) >= BAC_VAI[can]

# ---------- Máy tra cứu SOT (deterministic · không cần AI) ----------
def _deaccent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D")

def strip_accents(s):
    return _deaccent(s.lower())

STOPWORDS = set("la gi cua cho voi den tu va hay hoac thi ma o trong ngoai bao nhieu the nao khong duoc hien tai dang".split())

# Tách token: tên CamelCase (OmniSight, HeraHub, DualSight, SkyWatch...) trong nguồn dính thành
# 1 chữ, người dùng lại gõ tách rời ("Omni Sight") → cũ không khớp → honest-null oan (giấu tri
# thức đã có). Sửa GỐC: tách tại ranh giới thường→HOA / chữ→số TRƯỚC khi lowercase, phát CẢ phần
# tách LẪN dạng dính → cả "Omni Sight" và "OmniSight" đều khớp record. Generative (không hard-list
# tên sản phẩm — thêm sản phẩm mới tự khớp). Guard: chỉ phát segment tách khi len>=3 nên acronym
# ngắn (RtR→{rtr}, IP54→{ip54}) giữ nguyên dạng dính, không vỡ.
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+")
def tokens(s):
    out = []
    for word in re.findall(r"[A-Za-z0-9]+", _deaccent(s)):   # giữ hoa-thường để thấy ranh giới case
        segs = _CAMEL.findall(word)
        if len(segs) > 1:
            out.extend(seg.lower() for seg in segs if len(seg) >= 3)
        out.append(word.lower())                             # luôn giữ dạng dính (giữ acronym + entity)
    return [t for t in out if len(t) > 1 and t not in STOPWORDS]

# index sẵn + document frequency (từ hiếm đáng giá hơn từ phổ biến)
import math
DF = {}
for r in RECORDS:
    blob = " ".join(str(r.get(k, "")) for k in ("record", "content", "domain", "kernel_ref"))
    r["_tokens"] = set(tokens(blob))
    r["_blob"] = strip_accents(blob)
    for t in r["_tokens"]:
        DF[t] = DF.get(t, 0) + 1

N = len(RECORDS)
UBIQ_DF = 0.30 * N              # token ở >30% record là "phông nền" · không phân biệt được record nào
def is_ubiq(t):
    return DF.get(t, 0) > UBIQ_DF

def idf(t):
    return max(0.0, math.log((N + 1) / (DF.get(t, 0) + 1)) + 0.1)

# record mô tả spec/tài liệu thế hệ cũ: down-rank trong MOCK để số stale không đè số hiện hành.
# Marker hẹp và tường minh: "[spec cu" trong content hoặc rename-01 trong kernel_ref
# (KHÔNG dùng chữ "legacy" trần: record doctrine legacy 15 kg là câu trả lời hiện hành hợp lệ).
for r in RECORDS:
    r["_stale"] = ("[spec cu" in r["_blob"]) or ("rename-01" in strip_accents(str(r.get("kernel_ref", ""))))

# Hồ sơ tổng quan công ty: record định danh "RtR ... là công ty ..." · tìm theo mẫu content, KHÔNG hardcode id
# (nếu Lâm đổi wording bỏ "là công ty" thì fallback tự tắt, quay về honest-null — degrade an toàn).
OVERVIEW = next((r for r in RECORDS
                 if r.get("domain") == "company" and "la cong ty" in r["_blob"]), None)
STALE_PENALTY = 0.45  # nhân điểm · đủ tụt dưới record hiện hành cùng chủ đề, vẫn tra cứu được khi hỏi đích danh

# tên sản phẩm/hệ thống · dùng cho neo entity trong search
ENTITIES = {"hera", "vega", "herahub", "vegahub", "herasight", "vegasight",
            "omnisight", "dualsight", "heralink", "aerotunnel", "skywatch", "ragas"}

# record "catalog": nhắc NHIỀU sản phẩm cùng lúc (danh mục dropdown, bảng bảo dưỡng-mọi-sản-phẩm...)
# → khớp gần MỌI query sản phẩm nên hay thắng oan record spec tập trung khi hòa điểm (tie-break id).
# Đếm số entity mỗi record; khi người dùng hỏi ĐÍCH DANH 1 sản phẩm thì phạt catalog để spec thật lên.
# Generative (đếm entity, không hard-list id). Query hỏi "có những sản phẩm nào" không neo entity nên
# không dính phạt — catalog vẫn ra đúng lúc cần.
CATALOG_MIN = 4
for r in RECORDS:
    r["_nent"] = sum(1 for e in ENTITIES if e in r["_tokens"])

# đồng nghĩa hỏi-đáp → từ vựng trong gói (mở rộng query, không bịa đáp án)
SYNONYMS = [
    ("man hinh", ["nits", "lcd"]),
    ("sang gia bao nhieu nit", ["nits"]),
    ("tai trong", ["payload"]),
    ("payload", ["kg"]),          # hỏi payload là hỏi kg → record nói "14 kg" thắng record "5.7 lb"
    ("nang duoc", ["payload", "kg"]),
    ("patent", ["sang", "che", "patent"]),
    ("bang sang che", ["patent"]),
    ("ip rating", ["ip54", "ip43"]),
    ("chuan kin nuoc", ["ip54"]),
    ("slogan", ["signature"]),
    ("nâng", ["payload", "kg"]),  # trigger có dấu: match trên query gốc, tránh nhầm "năng lực"
    ("tool quan ly", ["control", "tower", "app"]),
    ("phan mem quan ly", ["control", "tower", "app"]),
    ("gia ban", ["gia", "duyet", "pricing"]),
    ("thanh lap", ["thanh", "lap", "nam"]),
    ("van phong", ["van", "phong", "cong", "van"]),
]

def expand(q_norm, q_tokens, q_raw=""):
    out = list(q_tokens)
    q_raw = q_raw.lower()
    for trigger, adds in SYNONYMS:
        hay = q_raw if any(ord(c) > 127 for c in trigger) else q_norm  # trigger có dấu match query gốc
        if trigger in hay:
            out.extend(a for a in adds if a not in out)
    return out

def search(query, top=3):
    q_norm = strip_accents(query)
    q_tokens = expand(q_norm, tokens(query), q_raw=query)
    if not q_tokens:
        return []
    triplets = re.findall(r"\d+-\d+-\d+", q_norm)  # dạng 1-4-14
    # neo entity nhận cả tên gõ TÁCH RỜI: "Dual Sight"/"Omni Sight" → bỏ dấu cách thành "dualsight"
    # để entity ghép hiện ra (nếu chỉ so token thì "dual"+"sight" mất neo, thua record OmniSight
    # cũng chứa "dual-pod"). Bỏ dấu cách trên query đã chuẩn hoá, entity nào là chuỗi con thì neo.
    q_despaced = q_norm.replace(" ", "")
    q_ents = [e for e in ENTITIES if e in q_tokens or e in q_despaced]
    # tài liệu văn phong (voice) là free-text rất dài → khớp gần mọi câu, thắng oan record fact.
    # Chỉ để nó nổi khi hỏi ĐÚNG về văn phong/giọng; còn lại phạt nặng như phông nền.
    q_voice = any(k in q_norm for k in ("van phong", "giong", "voice", "soan thao", "phong cach", "van phogn"))
    # giá vốn (BOM) chỉ nên DẪN khi hỏi đúng về giá vốn/chi phí; hỏi "X là gì" phải ra spec, không phải cost.
    q_cost = any(k in q_norm for k in ("gia von", "chi phi", "cost", "bom", "gia thanh", "gia linh kien"))
    scored = []
    for r in RECORDS:
        score = sum(idf(t) for t in q_tokens if t in r["_tokens"])
        score += sum(4.0 for tri in triplets if tri in r["_blob"])
        if len(q_norm) > 8 and q_norm in r["_blob"]:
            score += 3.0
        if r.get("domain") == "voice" and not q_voice:
            score *= 0.15
        if r.get("domain") == "cost" and not q_cost:
            score *= 0.15
        # neo entity: hỏi đích danh sản phẩm nào thì record không nhắc sản phẩm đó bị phạt nặng
        if q_ents and not any(e in r["_tokens"] for e in q_ents):
            score *= 0.25
        # catalog: hỏi đích danh 1 sản phẩm mà record là danh mục nhiều-sản-phẩm → phạt để spec thật lên
        if q_ents and len(q_ents) < CATALOG_MIN and r["_nent"] >= CATALOG_MIN:
            score *= 0.5
        if r["_stale"]:
            score *= STALE_PENALTY
        if score > 0:
            scored.append((round(score, 2), r))
    scored.sort(key=lambda x: (-x[0], x[1]["record"]))
    return scored[:top]

def confident(question, top_rec):
    """Trả lời hay honest null theo KHỐI LƯỢNG phân biệt, không đếm token thô.
    Token "phông nền" (ubiquitous, ở gần mọi record như 'rtr') KHÔNG tính — nếu câu
    hỏi chỉ khớp bằng token phông nền thì honest-null, không trả bừa record lạc đề.
    Ba cửa OR: khớp entity đích danh · 1 token rất hiếm · >=2 discriminator đủ khối lượng."""
    q_norm = strip_accents(question)
    q_tokens = expand(q_norm, tokens(question), q_raw=question)
    q_disc = [t for t in q_tokens if not is_ubiq(t)]   # token người dùng gõ, trừ phông nền
    if not q_disc:
        return False
    matched = [t for t in q_disc if t in top_rec["_tokens"]]
    cov = len(matched) / len(q_disc)
    if not matched or cov < 0.5:
        return False
    if any(e in matched for e in ENTITIES):            # khớp entity đích danh (hera, vega...) · tín hiệu mạnh
        return True
    if any(idf(t) >= 3.0 for t in matched):            # 1 token rất hiếm khớp · tín hiệu mạnh
        return True
    # không entity, không token hiếm → chỉ khớp bằng token vừa-hiếm → đòi phủ cao hơn để
    # chặn va chạm coincidental (vd "thời/Hỏa" đụng "thời điểm/Hoa Kỳ" trong record FCC)
    return len(matched) >= 2 and sum(idf(t) for t in matched) >= 3.0 and cov >= 0.66

def mock_answer(question):
    hits = search(question)
    if not hits or not confident(question, hits[0][1]):
        # Fallback định danh: câu hỏi CHỈ về "công ty là ai/gì" (không thuộc tính cụ thể nào)
        # → trả hồ sơ tổng quan thay vì honest-null. Bot công ty phải nói được mình là ai.
        # Chỉ kích hoạt khi query nhắc chính công ty VÀ không còn token nội dung nào ngoài "ai"
        # (who) — không đụng câu hỏi thuộc tính (giá, spec...) vốn phải honest-null nếu thiếu.
        qt = tokens(question)
        qd = [t for t in qt if not is_ubiq(t)]
        if OVERVIEW and ("rtr" in qt or "robotics" in qt) and set(qd) <= {"ai"}:
            return (f"[MOCK · máy tra cứu · chưa nối API · hồ sơ tổng quan công ty]\n"
                    f"{OVERVIEW['content']}\n[{OVERVIEW['record']}]")
        return (f"[MOCK · máy tra cứu · chưa nối API]\nSOT chưa có thông tin khớp câu hỏi này. "
                f"Câu hỏi đã được ghi nhận để curator bổ sung.\nGAP: {question.strip()[:150]}")
    parts = [f"[MOCK · máy tra cứu · chưa nối API · kết quả là record khớp nhất, không phải câu trả lời AI]"]
    top_score = hits[0][0]
    for score, r in hits[:2]:
        if score < 0.6 * top_score:
            break
        tag = f"[{r['record']}"
        if r.get("kernel_ref") and r["kernel_ref"] not in ("null", "None", ""):
            tag += f" · {r['kernel_ref']}"
        tag += "]"
        label = ""
        if "PROPOSED" in str(r.get("label", "")) + str(r.get("content", "")):
            label = "\n(PROPOSED · chưa cam kết với khách)"
        if r.get("_stale"):
            label += "\n(Cảnh báo: record mô tả spec/tài liệu thế hệ CŨ · không dùng số này làm hiện hành · xác nhận bằng chế độ LIVE)"
        if r.get("canh_bao"):
            label += f"\n({r['canh_bao']})"
        parts.append(f"{r['content']}\n{tag}{label}")
    return "\n\n".join(parts)

# ---------- LIVE mode ----------
def call_claude_stream(messages, on_text):
    """Gọi API ở chế độ chảy dần · trả về toàn văn sau khi xong.
    on_text(chunk) được gọi mỗi mẩu chữ để server đẩy tiếp cho trình duyệt."""
    body = json.dumps({"model": MODEL, "max_tokens": 1500, "system": SYSTEM,
                       "messages": messages, "stream": True}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    full = []
    with urllib.request.urlopen(req, timeout=180) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "content_block_delta":
                t = (ev.get("delta") or {}).get("text", "")
                if t:
                    full.append(t)
                    on_text(t)
    return "".join(full)


def call_claude(messages):
    body = json.dumps({"model": MODEL, "max_tokens": 1500, "system": SYSTEM, "messages": messages}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", []))

# ---------- UI ----------
# ---------- UI ----------
# Giao diện dựng theo Design DNA Playbook v1.0, để riêng file cho dễ sửa và soi.
_ui = HERE / "ui.html"
if not _ui.exists():
    sys.exit("Không tìm thấy ui.html cạnh copilot_server.py")
HTML = _ui.read_text(encoding="utf-8")


def group_gaps(rows):
    """Gom câu hỏi GAP cùng chủ đề · cùng luật với weekly_review (>=2 từ nội dung chung)."""
    STOP = set("""bao nhieu the nao la gi cua cho voi den tu va hay hoac thi ma trong ngoai khong duoc
hien tai dang cong ty minh chung toi anh chi em xin hoi cai con nay kia do day ra vao len xuong
mot hai ba may sao vay nhi nhe oi khi lam sau truoc nua roi chua co phai can biet noi""".split())
    def toks(q):
        return set(w for w in re.sub(r"[^a-z0-9 ]", " ", strip_accents(q)).split()
                   if len(w) > 2 and w not in STOP)
    items = [(r.get("gap") or r.get("q", ""), toks(r.get("gap") or r.get("q", "")), r.get("t", ""))
             for r in rows]
    used, groups = set(), []
    for i, (q, tk, t) in enumerate(items):
        if i in used or not tk:
            continue
        grp, last = [q], t
        used.add(i)
        for j in range(i + 1, len(items)):
            if j in used or not items[j][1]:
                continue
            if len(tk & items[j][1]) >= 2:
                grp.append(items[j][0]); last = max(last, items[j][2]); used.add(j)
        variants = [v for v in dict.fromkeys(grp[1:]) if v != grp[0]]
        groups.append({"q": grp[0], "count": len(grp), "variants": variants,
                       "last": (last or "")[:10]})
    groups.sort(key=lambda g: -g["count"])
    return groups


PACK_DATE = (re.search(r"ngay_sinh: '?([\d-]+)'?", GOI_TEXT) or [None, "?"])[1]

# ---------- Document Studio · vá bản mẫu (NT-4) ----------
sys.path.insert(0, str(HERE.parent / "tools"))
try:
    import render_doc
    TEMPLATES = render_doc.load_yaml(HERE.parent / "templates" / "registry.yaml")["templates"]
except Exception as _e:          # thiếu bản mẫu thì màn Tạo tài liệu báo rõ, không sập server
    render_doc, TEMPLATES = None, []
    print(f"CHÚ Ý: chưa nạp được bộ sinh tài liệu ({_e}) · màn Tạo tài liệu sẽ báo chưa sẵn sàng")

RENDER_DIR = HERE.parent / "_rendered"

# Bản mẫu nào mang tư cách pháp nhân · SUY RA từ registry, không viết tay danh sách id.
# Viết tay là chắc chắn quên khi ai đó thêm bản mẫu "tờ trình" hay "báo cáo gửi Bộ":
# bản mẫu mới sẽ lọt xuống vai nhân viên mà không ai kịp thấy.
# Dấu hiệu: bản mẫu có trường khoá NGƯỜI KÝ. Tên công ty thì fact-sheet và slide card
# cũng có (in trên đầu trang, vô hại); chữ ký CEO thì chỉ văn bản ràng buộc mới có.
CONG_VAN_IDS = {t["id"] for t in TEMPLATES
                if any(f.get("key") == "nguoi_ky" and f.get("type") == "locked"
                       for f in t.get("fields", []))}


_KH_CSS = """body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0d0f11;
color:#e8e6e3;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.k{max-width:520px;padding:40px;border:1px solid #23272b;border-radius:14px;background:#131619}
h1{font-size:20px;margin:0 0 4px}p{color:#a9b0b6}a{color:#e8e6e3}
input{width:100%;box-sizing:border-box;padding:11px 12px;background:#0d0f11;border:1px solid #23272b;
color:#e8e6e3;font:inherit;font-size:14px;margin-top:10px}
button{width:100%;height:38px;margin-top:12px;background:#e8e6e3;color:#0d0f11;border:0;
font:inherit;font-weight:600;font-size:14px;cursor:pointer}
.m{margin:16px 0 0;padding:14px 16px;border-left:2px solid currentColor;background:#171b1e}
.e{color:#d97070;font-size:13px;min-height:18px;margin-top:8px}"""


def _khung(tieu_de, mau, than):
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{tieu_de} · RtR Copilot</title><style>{_KH_CSS}</style></head>
<body><div class="k"><h1 style="color:{mau}">{tieu_de}</h1>{than}
<p style="margin-top:24px;font-size:13px"><a href="/">← Về RtR Copilot</a></p></div></body></html>"""


def _trang_kich_hoat(ma):
    """Trang sau khi bấm link · hai loại link, hai màn khác nhau.

    Người TỰ ĐĂNG KÝ đã có mật khẩu → bấm link là xong.
    Người ĐƯỢC MỜI TAY chưa có mật khẩu → phải hiện ô đặt mật khẩu, và tuyệt đối
    KHÔNG được tiêu mã ở bước hiển thị, nếu không mở link ra là mất luôn đường vào.
    """
    if not auth:
        return 400, _khung("Không kích hoạt được", "#d97070",
                           '<div class="m">Máy chủ chưa bật tài khoản</div>')
    loai, acc, loi = auth.trang_thai_ma(ma)
    if loai == "dat_mat_khau":
        than = (f'<p>Chào <b>{acc["ten"]}</b>. Đặt mật khẩu để bắt đầu dùng RtR Copilot '
                f'với quyền <b>{auth.NHAN_VAI[acc["quyen"]]}</b>.</p>'
                '<form method="POST" action="/kichhoat">'
                f'<input type="hidden" name="ma" value="{ma}">'
                f'<input type="password" name="mk" placeholder="Mật khẩu · tối thiểu {auth.MIN_PW} ký tự" '
                'autocomplete="new-password" autofocus>'
                '<button type="submit">Đặt mật khẩu và vào</button></form>'
                '<p style="font-size:12px;margin-top:18px">Câu hỏi của bạn có ghi lại kèm tên, và '
                '<b>chỉ quản trị viên</b> đọc được phần kèm tên. Lãnh đạo chỉ thấy số liệu tổng hợp.</p>')
        return 200, _khung("Đặt mật khẩu", "#e8e6e3", than)
    if loai == "kich_hoat":
        ok, msg = auth.kich_hoat(ma)
        if ok:
            return 200, _khung("Kích hoạt thành công", "#4ea87b",
                               f'<div class="m" style="color:#4ea87b">{msg}</div>'
                               '<p>Quay lại ứng dụng và đăng nhập bằng email của bạn. Quyền cao hơn '
                               'do quản trị viên cấp riêng.</p>')
        loi = msg
    return 400, _khung("Không kích hoạt được", "#d97070",
                       f'<div class="m" style="color:#d97070">{loi}</div>'
                       '<p>Link quá hạn thì xin quản trị viên cấp lại, hoặc đăng ký lại từ màn hình đăng nhập.</p>')


def _dat_mat_khau_moi(ma, mk):
    ok, msg = auth.kich_hoat(ma, mk) if auth else (False, "Máy chủ chưa bật tài khoản")
    if ok:
        return 200, _khung("Xong", "#4ea87b",
                           f'<div class="m" style="color:#4ea87b">{msg}</div>'
                           '<p>Quay lại ứng dụng và đăng nhập bằng email của bạn.</p>')
    # Sai mật khẩu thì hiện LẠI ô nhập, không đá người dùng về trang lỗi cụt:
    # mã vẫn còn hiệu lực, chỉ là họ gõ chưa đủ dài.
    loai, acc, _ = auth.trang_thai_ma(ma)
    if loai == "dat_mat_khau":
        than = (f'<p>Chào <b>{acc["ten"]}</b>.</p><div class="e">{msg}</div>'
                '<form method="POST" action="/kichhoat">'
                f'<input type="hidden" name="ma" value="{ma}">'
                f'<input type="password" name="mk" placeholder="Mật khẩu · tối thiểu {auth.MIN_PW} ký tự" '
                'autocomplete="new-password" autofocus>'
                '<button type="submit">Đặt mật khẩu và vào</button></form>')
        return 400, _khung("Đặt mật khẩu", "#e8e6e3", than)
    return 400, _khung("Không kích hoạt được", "#d97070",
                       f'<div class="m" style="color:#d97070">{msg}</div>')


def read_jsonl(path, limit=None):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-limit:] if limit else out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("content-type", ctype + "; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, HTML, "text/html")
        if self.path == "/health":
            return self._send(200, json.dumps({
                "ok": True, "mode": MODE, "pack": PACK, "dang_nhap": bool(USERS),
                "model": MODEL if MODE == "LIVE" else None,
                "records_loaded": len(RECORDS), "pack_date": PACK_DATE}))
        if self.path.startswith("/api/search"):
            q = urllib.request.unquote(self.path.split("q=", 1)[-1]) if "q=" in self.path else ""
            hits = search(q, top=8)
            out = [{k: r.get(k) for k in ("record", "content", "domain", "tier", "status")} for _, r in hits]
            return self._send(200, json.dumps({"results": out}, ensure_ascii=False))
        if self.path == "/api/templates":
            out = [{k: t.get(k) for k in ("id", "name", "desc", "kind", "category", "version")}
                   | {"fields": [{kk: f.get(kk) for kk in
                                  ("key", "label", "type", "required", "multiline", "hint",
                                   "format", "default", "record", "value", "note")}
                                 for f in t["fields"] if f["type"] != "derived"]}
                   for t in TEMPLATES]
            return self._send(200, json.dumps({"ready": bool(TEMPLATES), "templates": out},
                                              ensure_ascii=False))
        if self.path.startswith("/api/download"):
            name = urllib.request.unquote(self.path.split("f=", 1)[-1]) if "f=" in self.path else ""
            f = (RENDER_DIR / Path(name).name)          # chặn đi ra ngoài thư mục
            if not f.exists() or f.parent != RENDER_DIR:
                return self._send(404, json.dumps({"error": "không có file"}))
            ctype = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                     if f.suffix == ".docx" else
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-disposition", f'attachment; filename="{f.name}"')
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/api/whoami":
            ok, user, err = who(self)
            # Trả kèm bảng quyền đã tính sẵn để giao diện ẩn/hiện đúng. Đây CHỈ là
            # trang trí — mọi cổng thật nằm ở phía server; giấu nút không phải là khoá.
            lam_duoc = {k: duoc_lam(user, k) for k in BANG_QUYEN} if ok else {}
            return self._send(200, json.dumps(
                {"ok": ok, "can_dang_nhap": dung_tai_khoan() or bool(USERS),
                 "che_do_dang_nhap": "tai_khoan" if dung_tai_khoan()
                                     else ("ma_rieng" if USERS else "ma_chung"),
                 "cho_dang_ky": bool(auth) and dung_tai_khoan(),
                 "user": user, "lam_duoc": lam_duoc, "error": err},
                ensure_ascii=False))
        if self.path.startswith("/kichhoat"):
            ma = urllib.request.unquote(self.path.split("ma=", 1)[-1]) if "ma=" in self.path else ""
            code, body = _trang_kich_hoat(ma)
            return self._send(code, body, "text/html")
        if self.path == "/api/admin/users":
            ok, user, err = who(self)
            if not ok:
                return self._send(403, json.dumps({"error": err}, ensure_ascii=False))
            if not duoc_lam(user, "quan_tri_nguoi_dung"):
                return self._send(403, json.dumps(
                    {"error": "Chỉ quản trị viên xem được danh sách tài khoản"}, ensure_ascii=False))
            rows = [auth.cong_khai(a, day_du=True) for a in auth.tat_ca()] if auth else []
            rows.sort(key=lambda r: (r["trang_thai"] != "cho_kich_hoat", r["ten"].lower()))
            return self._send(200, json.dumps(
                {"users": rows, "thong_ke": auth.thong_ke() if auth else {},
                 "smtp": bool(auth and auth.smtp_san_sang()),
                 "ten_mien": auth.DOMAINS if auth else []}, ensure_ascii=False))
        if self.path == "/api/issues":
            ok, user, err = who(self)
            if not ok:
                return self._send(403, json.dumps({"error": err}, ensure_ascii=False))
            rows = read_jsonl(ISSUE_LOG)
            for i, r in enumerate(rows):
                r["idx"] = i
            # Ai thấy gì · Lâm chốt 29/07: chỉ quản trị viên đọc được ca kèm TÊN người báo.
            # Lãnh đạo duyệt được nội dung nhưng không biết ai báo; nhân viên chỉ thấy ca
            # của chính mình để theo dõi việc mình đã báo.
            if duoc_lam(user, "xem_ten_nguoi_hoi"):
                pass
            elif duoc_lam(user, "duyet_bao_sai"):
                rows = [dict(r, nguoi="(ẩn danh)") for r in rows]
            else:
                ten = (user or {}).get("ten", "")
                rows = [r for r in rows if r.get("nguoi") == ten]
            return self._send(200, json.dumps({"issues": list(reversed(rows)),
                                               "an_danh": not duoc_lam(user, "xem_ten_nguoi_hoi"),
                                               "chi_cua_toi": not duoc_lam(user, "duyet_bao_sai")},
                                              ensure_ascii=False))
        if self.path == "/api/gaps":
            return self._send(200, json.dumps({"groups": group_gaps(read_jsonl(GAP_LOG))},
                                              ensure_ascii=False))
        if self.path == "/api/audit":
            ok, user, err = who(self)
            if not ok:
                return self._send(403, json.dumps({"error": err}, ensure_ascii=False))
            # Ba mức nhìn · quyết định của Lâm 29/07 về quyền riêng tư người hỏi.
            # Lý do không phải hình thức: người ta chỉ dám hỏi câu ngây thơ khi biết
            # sếp không đọc được tên mình bên cạnh câu hỏi đó. Mà chính câu ngây thơ
            # mới lộ ra chỗ tài liệu công ty đang thủng.
            xem_ten = duoc_lam(user, "xem_ten_nguoi_hoi")
            xem_het = duoc_lam(user, "xem_thong_ke")
            ten_toi = (user or {}).get("ten", "")
            evs = []
            for r in reversed(read_jsonl(QA_LOG, limit=200)):
                if not xem_het and r.get("nguoi", "không rõ") != ten_toi:
                    continue
                a = r.get("a", "")
                gate = "HONEST NULL" if "GAP:" in a else ("MOCK LOOKUP" if r.get("mode") == "MOCK" else "PASS")
                e = {"t": r.get("t", ""), "q": r.get("q", ""), "a": a,
                     "mode": r.get("mode", ""), "gate": gate}
                if xem_ten:
                    e["nguoi"] = r.get("nguoi", "không rõ")
                evs.append(e)
                if len(evs) >= 60:
                    break
            return self._send(200, json.dumps(
                {"events": evs, "co_ten": xem_ten,
                 "pham_vi": "tat_ca" if xem_het else "chi_cua_toi"}, ensure_ascii=False))
        if self.path.startswith("/api/usedby"):
            rid = urllib.request.unquote(self.path.split("id=", 1)[-1]) if "id=" in self.path else ""
            uses = []
            for r in reversed(read_jsonl(QA_LOG, limit=200)):
                if rid and rid in (r.get("a") or ""):
                    uses.append({"t": r.get("t", ""), "q": r.get("q", "")})
                if len(uses) >= 8:
                    break
            return self._send(200, json.dumps({"uses": uses}, ensure_ascii=False))
        if self.path.startswith("/api/record"):
            rid = urllib.request.unquote(self.path.split("id=", 1)[-1]) if "id=" in self.path else ""
            r = BY_ID.get(rid)
            if not r:
                return self._send(404, json.dumps({"error": "record không tồn tại"}))
            out = {k: v for k, v in r.items() if not k.startswith("_")}
            out["stale"] = bool(r.get("_stale"))
            return self._send(200, json.dumps(out, ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))

    def _body(self):
        length = int(self.headers.get("content-length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def _goc_url(self):
        """Địa chỉ người dùng đang gõ · để link kích hoạt trong thư trỏ đúng máy."""
        host = self.headers.get("host") or f"127.0.0.1:{PORT}"
        return os.environ.get("COPILOT_URL", "").strip().rstrip("/") or f"http://{host}"

    def do_POST(self):
        if self.path.startswith("/kichhoat"):
            # Form đặt mật khẩu của người được mời tay · gửi dạng form thường để trang
            # kích hoạt không cần JavaScript: người nhận có thể mở trên điện thoại cũ.
            raw = self.rfile.read(int(self.headers.get("content-length", 0))).decode()
            f = urllib.parse.parse_qs(raw)
            code, body = _dat_mat_khau_moi(f.get("ma", [""])[0], f.get("mk", [""])[0])
            return self._send(code, body, "text/html")

        # ---------- tài khoản · KHÔNG cần đăng nhập trước ----------
        if self.path in ("/api/dangky", "/api/dangnhap"):
            if not auth:
                return self._send(503, json.dumps({"error": "Chưa bật tài khoản trên máy chủ này"},
                                                  ensure_ascii=False))
            try:
                b = self._body()
            except Exception:
                return self._send(400, json.dumps({"error": "Dữ liệu gửi lên không đọc được"}))
            if self.path == "/api/dangky":
                ok, msg = auth.dang_ky(b.get("email"), b.get("ten"), b.get("mat_khau"),
                                       self._goc_url())
                return self._send(200 if ok else 400,
                                  json.dumps({"ok": ok, "thong_bao" if ok else "error": msg},
                                             ensure_ascii=False))
            tok, err, acc = auth.dang_nhap(b.get("email"), b.get("mat_khau"))
            if not tok:
                return self._send(401, json.dumps({"error": err}, ensure_ascii=False))
            return self._send(200, json.dumps(
                {"ok": True, "token": tok, "user": auth.cong_khai(acc),
                 "lam_duoc": {k: auth.duoc(acc, k) for k in auth.QUYEN},
                 "het_han_gio": auth.TOKEN_TTL_H}, ensure_ascii=False))

        if self.path == "/api/doimatkhau":
            ok, user, err = who(self)
            if not ok or not auth:
                return self._send(403, json.dumps({"error": err or "Chưa đăng nhập"},
                                                  ensure_ascii=False))
            acc = auth.tim(user.get("email", ""))
            if not acc:
                return self._send(400, json.dumps({"error": "Chỉ tài khoản email đổi được mật khẩu"},
                                                  ensure_ascii=False))
            b = self._body()
            done, msg = auth.doi_mat_khau(acc, b.get("cu"), b.get("moi"))
            return self._send(200 if done else 400,
                              json.dumps({"ok": done, "thong_bao" if done else "error": msg},
                                         ensure_ascii=False))

        if self.path == "/api/admin/moi":
            ok, user, err = who(self)
            if not ok:
                return self._send(403, json.dumps({"error": err}, ensure_ascii=False))
            if not duoc_lam(user, "quan_tri_nguoi_dung") or not auth:
                return self._send(403, json.dumps(
                    {"error": "Chỉ quản trị viên mời được người mới"}, ensure_ascii=False))
            b = self._body()
            boi = user.get("email") or user.get("ten", "?")
            done, msg, extra = auth.moi(b.get("email"), b.get("ten"),
                                        b.get("vai") or "nhanvien", boi, self._goc_url())
            if done:
                with QA_LOG.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"),
                                        "mode": MODE, "nguoi": boi,
                                        "q": f"[QUẢN TRỊ] mời {b.get('email')} vai {b.get('vai')}",
                                        "a": msg}, ensure_ascii=False) + "\n")
            return self._send(200 if done else 400, json.dumps(
                {"ok": done, **({"thong_bao": msg, **(extra or {})} if done else {"error": msg})},
                ensure_ascii=False))

        if self.path in ("/api/admin/vai", "/api/admin/khoa"):
            ok, user, err = who(self)
            if not ok:
                return self._send(403, json.dumps({"error": err}, ensure_ascii=False))
            if not duoc_lam(user, "quan_tri_nguoi_dung") or not auth:
                return self._send(403, json.dumps(
                    {"error": "Chỉ quản trị viên phân quyền được"}, ensure_ascii=False))
            b = self._body()
            boi = user.get("email") or user.get("ten", "?")
            if self.path == "/api/admin/vai":
                done, msg = auth.dat_vai(b.get("email"), b.get("vai"), boi)
            else:
                done, msg = auth.dat_khoa(b.get("email"), bool(b.get("khoa")), boi)
            if done:
                with QA_LOG.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"),
                                        "mode": MODE, "nguoi": boi,
                                        "q": f"[QUẢN TRỊ] {self.path.rsplit('/', 1)[-1]} · {b.get('email')}",
                                        "a": msg}, ensure_ascii=False) + "\n")
            return self._send(200 if done else 400,
                              json.dumps({"ok": done, "thong_bao" if done else "error": msg},
                                         ensure_ascii=False))

        if self.path == "/api/issue":
            # Báo sai phải thành DỮ LIỆU, không phải một thông báo rồi thôi.
            # Sổ theo dõi 4 tuần có ô "số ca báo sai" · đây là đường đổ vào ô đó.
            ok, user, err = who(self)
            if not ok:
                return self._send(403, json.dumps({"error": err}, ensure_ascii=False))
            try:
                length = int(self.headers.get("content-length", 0))
                b = json.loads(self.rfile.read(length))
                q = (b.get("q") or "").strip()[:500]
                a = (b.get("a") or "").strip()[:2000]
                why = (b.get("why") or "").strip()[:1000]
                if not q and not a:
                    return self._send(400, json.dumps({"error": "Thiếu nội dung câu trả lời bị báo sai"}))
                rec = {"t": datetime.now().isoformat(timespec="seconds"), "mode": MODE, "pack": PACK,
                       "nguoi": (user or {}).get("ten", "không rõ"),
                       "q": q, "a": a, "why": why,
                       "records": re.findall(r"\[((?:HC|OC|SC|STRAT|L3F|L3R|CAND|SPEC|DISP|PRICE)[-.][^\]\s·]*)", a),
                       "trang_thai": "moi"}
                with ISSUE_LOG.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                return self._send(200, json.dumps({"ok": True, "records": rec["records"]},
                                                  ensure_ascii=False))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)[:200]}))
        if self.path == "/api/extract":
            # NT-4: model CHỈ bóc tham số từ lời người dùng · không tạo file, không
            # đụng fact khoá. Kết quả đổ vào form để NGƯỜI soát rồi mới bấm xuất.
            ok, user, err = who(self)
            if not ok:
                return self._send(403, json.dumps({"error": err}, ensure_ascii=False))
            if MODE != "LIVE":
                return self._send(200, json.dumps(
                    {"ok": False, "reason": "Bóc tham số cần chế độ LIVE · chưa nối API key. "
                                            "Điền tay như thường."}, ensure_ascii=False))
            try:
                length = int(self.headers.get("content-length", 0))
                b = json.loads(self.rfile.read(length))
                tid = b.get("template", "")
                yeu_cau = (b.get("text") or "").strip()[:4000]
                tpl = next((t for t in TEMPLATES if t["id"] == tid), None)
                if not tpl or not yeu_cau:
                    return self._send(400, json.dumps({"error": "Thiếu bản mẫu hoặc nội dung yêu cầu"}))
                fields = [f for f in tpl["fields"] if f["type"] == "user"]
                mota = "\n".join(f"- {f['key']}: {f['label']}"
                                 + (f" · {f['hint']}" if f.get("hint") else "")
                                 + (" · dạng ngày YYYY-MM-DD" if f.get("format") == "date" else "")
                                 for f in fields)
                prompt = (
                    "Bóc tham số từ yêu cầu của người dùng để điền vào biểu mẫu. "
                    "Trả về DUY NHẤT một khối JSON, không giải thích.\n\n"
                    f"Các trường cần điền:\n{mota}\n\n"
                    "Luật:\n"
                    "- Trường nào yêu cầu KHÔNG nói rõ thì để chuỗi rỗng. TUYỆT ĐỐI không suy đoán, "
                    "không bịa số công văn, không bịa ngày, không bịa tên cơ quan.\n"
                    "- Không lấy thông tin từ gói tri thức để điền vào đây; chỉ lấy từ lời người dùng.\n"
                    "- Giữ nguyên văn phong tiếng Việt của người dùng cho các trường nội dung dài.\n\n"
                    f"Yêu cầu của người dùng:\n{yeu_cau}")
                raw = call_claude([{"role": "user", "content": prompt}])
                m = re.search(r"\{.*\}", raw, re.S)
                data = json.loads(m.group(0)) if m else {}
                keys = {f["key"] for f in fields}
                out = {k: str(v) for k, v in data.items() if k in keys and str(v).strip()}
                with QA_LOG.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"),
                                        "mode": MODE, "nguoi": (user or {}).get("ten", "không rõ"),
                                        "q": f"[BÓC THAM SỐ] {tid}: {yeu_cau[:120]}",
                                        "a": f"điền sẵn {len(out)}/{len(fields)} trường"},
                                       ensure_ascii=False) + "\n")
                return self._send(200, json.dumps(
                    {"ok": True, "params": out, "so_truong": len(fields)}, ensure_ascii=False))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)[:250]}, ensure_ascii=False))
        if self.path == "/api/render":
            ok, user, err = who(self)
            if not ok:
                return self._send(403, json.dumps({"error": err}, ensure_ascii=False))
            if not render_doc:
                return self._send(500, json.dumps(
                    {"state": "FAIL-LOUD", "issues": ["Bộ sinh tài liệu chưa nạp được"]},
                    ensure_ascii=False))
            try:
                length = int(self.headers.get("content-length", 0))
                body = json.loads(self.rfile.read(length))
                tid = body.get("template", "")
                params = body.get("params", {}) or {}
                dry = bool(body.get("dry_run"))
                # Công văn mang TƯ CÁCH PHÁP NHÂN: có tên công ty, số công văn và
                # chữ ký CEO. Một file như thế gửi ra cơ quan nhà nước là ràng buộc
                # công ty. Fact-sheet hay sales brief thì không — nên chỉ khoá công văn.
                if tid in CONG_VAN_IDS and not duoc_lam(user, "sinh_cong_van"):
                    return self._send(403, json.dumps(
                        {"state": "FAIL-LOUD", "issues": [
                            "Công văn mang tư cách pháp nhân · chỉ lãnh đạo trở lên tạo được. "
                            "Bạn vẫn tạo được fact-sheet, slide card và sales brief."]},
                        ensure_ascii=False))
                if dry:
                    state, values, issues, _ = render_doc.resolve(tid, params)
                    return self._send(200, json.dumps(
                        {"state": state, "issues": issues,
                         "locked": {k: v for k, v in values.items() if v != ""}},
                        ensure_ascii=False))
                r = render_doc.render(tid, params, out_dir=RENDER_DIR)
                if r.get("file"):
                    r["download"] = "/api/download?f=" + urllib.request.quote(Path(r["file"]).name)
                    r["filename"] = Path(r["file"]).name
                    r.pop("file", None)
                    with QA_LOG.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"),
                                            "mode": MODE, "q": f"[TẠO TÀI LIỆU] {tid}",
                                            "a": f"{r['state']} · {r['filename']} · record: "
                                                 f"{', '.join(r.get('records') or []) or 'không có fact khoá'}"},
                                           ensure_ascii=False) + "\n")
                return self._send(200, json.dumps(r, ensure_ascii=False))
            except Exception as e:
                return self._send(500, json.dumps(
                    {"state": "FAIL-LOUD", "issues": [str(e)[:300]]}, ensure_ascii=False))
        if self.path != "/api/chat":
            return self._send(404, json.dumps({"error": "not found"}))
        ok, user, err = who(self)
        if not ok:
            return self._send(403, json.dumps({"error": err}, ensure_ascii=False))
        streamed = False
        try:
            length = int(self.headers.get("content-length", 0))
            payload = json.loads(self.rfile.read(length))
            messages = payload.get("messages", [])[-20:]
            question = messages[-1]["content"] if messages else ""   # câu hỏi SẠCH · dùng để log
            note = (payload.get("note") or "").strip()[:2000]
            if note and messages:
                # Ghép chỉ cho lần gọi API này. KHÔNG chạm SYSTEM (nguồn tri thức),
                # KHÔNG lưu vào log: ghi chú là bối cảnh riêng của người hỏi, không
                # phải fact, và không được lọt vào hàng đợi thu-fact của curator.
                messages = messages[:-1] + [{
                    "role": "user",
                    "content": question + "\n\n[Ghi chú người dùng kèm câu hỏi này · KHÔNG phải fact "
                               "đã duyệt trong SOT · chỉ dùng làm bối cảnh; nếu mâu thuẫn với SOT thì "
                               "ưu tiên SOT và nói rõ]\n" + note}]
            want_stream = bool(payload.get("stream")) and MODE == "LIVE"
            if MODE == "MOCK":
                answer = mock_answer(question)
            elif want_stream:
                # Chảy dần: mở dòng SSE rồi đẩy từng mẩu. Người dùng thấy chữ hiện
                # ngay thay vì chờ cả câu · huỷ giữa chừng = trình duyệt ngắt kết nối.
                self.send_response(200)
                self.send_header("content-type", "text/event-stream; charset=utf-8")
                self.send_header("cache-control", "no-cache")
                self.end_headers()
                streamed = True

                def push(chunk):
                    self.wfile.write(b"data: " + json.dumps({"t": chunk}, ensure_ascii=False).encode() + b"\n\n")
                    self.wfile.flush()

                answer = call_claude_stream(messages, push)
                self.wfile.write(b"data: " + json.dumps({"done": True}).encode() + b"\n\n")
                self.wfile.flush()
            else:
                answer = call_claude(messages)
        except (BrokenPipeError, ConnectionResetError):
            # Người dùng bấm dừng · trình duyệt ngắt kết nối. KHÔNG ghi log, không
            # phải lỗi hệ thống. Phải đứng TRƯỚC `except Exception` vì nó là lớp con:
            # đặt sau thì không bao giờ chạy (handler chết).
            return
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            if e.code in (400, 404) and "model" in detail.lower():
                return self._send(500, json.dumps({"error":
                    f"Model '{MODEL}' không khả dụng với API key này. Đổi model không sửa code: "
                    f"tắt server, export COPILOT_MODEL=<model account có> rồi chạy lại."}, ensure_ascii=False))
            return self._send(500, json.dumps({"error": f"API {e.code}: {detail}"}, ensure_ascii=False))
        except Exception as e:
            if streamed:
                return  # đã mở dòng SSE · không gửi JSON lỗi đè lên nữa
            return self._send(500, json.dumps({"error": str(e)[:300]}))

        now = datetime.now().isoformat(timespec="seconds")
        with QA_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": now, "mode": MODE, "nguoi": (user or {}).get("ten", "không rõ"),
                                "q": question, "a": answer}, ensure_ascii=False) + "\n")
        for gap in re.findall(r"GAP:\s*(.+)", answer):
            with GAP_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": now, "gap": gap.strip(), "q": question}, ensure_ascii=False) + "\n")
        if not streamed:
            self._send(200, json.dumps({"answer": answer}, ensure_ascii=False))


if __name__ == "__main__":
    # Mở ra LAN khi CÓ cách nhận diện người: passcode chung, hoặc đã có tài khoản thật.
    HOST = "0.0.0.0" if (PASSCODE or dung_tai_khoan()) else "127.0.0.1"
    if not PASSCODE and not dung_tai_khoan():
        print("CHÚ Ý: chưa có tài khoản nào và chưa set COPILOT_PASSCODE · chỉ bind 127.0.0.1.")
        print("Mở cho LAN: tạo tài khoản quản trị (COPILOT_ADMIN_EMAIL + đăng ký) hoặc")
        print("            export COPILOT_PASSCODE=matma rồi chạy lại.")
    if PACK == "leader":
        print("=" * 66)
        print("GÓI LÃNH ĐẠO · chứa giá bán và chính sách chiết khấu.")
        print("Chỉ chia sẻ địa chỉ và passcode cho nhóm đã được cấp quyền.")
        print("=" * 66)
    if dung_tai_khoan():
        _tk = auth.thong_ke()
        print(f"Đăng nhập: TÀI KHOẢN EMAIL · {_tk['hoat_dong']} hoạt động "
              f"({_tk['theo_vai']['quantri']} quản trị · {_tk['theo_vai']['lanhdao']} lãnh đạo · "
              f"{_tk['theo_vai']['nhanvien']} nhân viên) · {_tk['cho_kich_hoat']} chờ kích hoạt")
        print(f"Tự đăng ký: {', '.join('@' + d for d in auth.DOMAINS)}")
        if not auth.smtp_san_sang():
            print("CHÚ Ý: CHƯA cấu hình SMTP · người mới KHÔNG đăng ký được (không gửi được thư "
                  "kích hoạt). Khai COPILOT_SMTP_HOST/USER/PASS.")
    elif USERS:
        print(f"Đăng nhập: {len(USERS)} người trong users.yaml (đường lùi · nên chuyển sang tài khoản email)")
    else:
        print("Đăng nhập: chưa có tài khoản nào · dùng passcode chung (không đếm được người dùng thực)")
        if auth and auth.ADMIN_EMAIL:
            print(f"Quản trị viên gốc sẽ là {auth.ADMIN_EMAIL} khi đăng ký lần đầu.")
        elif auth:
            print("CHÚ Ý: chưa khai COPILOT_ADMIN_EMAIL · đăng ký xong sẽ KHÔNG có ai phân quyền được.")
    print(f"RtR Copilot · http://{HOST}:{PORT} · gói {PACK} · chế độ {MODE}" + (f" · model {MODEL}" if MODE == "LIVE" else " · cắm ANTHROPIC_API_KEY để LIVE"))
    print(f"Gói: {len(RECORDS)} record · SOT {PACK_DATE}")
    HTTPServer((HOST, PORT), Handler).serve_forever()
