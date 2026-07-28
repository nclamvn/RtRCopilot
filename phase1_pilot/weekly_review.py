#!/usr/bin/env python3
"""Báo cáo thứ Sáu · đọc log pilot sinh sẵn số liệu cho sổ theo dõi 4 tuần.

    python3 weekly_review.py              # tuần gần nhất (7 ngày)
    python3 weekly_review.py --tuan 2     # đánh số tuần cho tiêu đề
    python3 weekly_review.py --tu 2026-08-01 --den 2026-08-07

Đọc qa_log.jsonl + gap_log.jsonl (server tự ghi) → in báo cáo markdown ra màn hình
và ghi vào bao_cao_tuan/ để dán vào 04_So_Theo_Doi_4_Tuan.md.

Nguyên tắc: chỉ đếm cái đếm được. Số nào cần người đánh giá (ca báo sai, use case lặp)
để trống kèm nhắc, KHÔNG đoán.
"""
import argparse
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
QA_LOG = HERE / "qa_log.jsonl"
GAP_LOG = HERE / "gap_log.jsonl"
ISSUE_LOG = HERE / "issue_log.jsonl"
OUTDIR = HERE / "bao_cao_tuan"


def load(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def in_range(row, start, end):
    try:
        t = datetime.fromisoformat(row.get("t", ""))
    except ValueError:
        return False
    return start <= t <= end


def norm(s):
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower())
                if unicodedata.category(c) != "Mn").replace("đ", "d")
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


# Từ khung câu hỏi · không mang nội dung, không được dùng làm căn cứ gom nhóm.
STOP = set("""bao nhieu the nao la gi cua cho voi den tu va hay hoac thi ma trong ngoai khong duoc
hien tai dang cong ty minh chung toi anh chi em xin hoi cai con nay kia do day ra vao len xuong
mot hai ba may sao vay nhi nhe a oi khi lam sau truoc nua roi chua co phai can biet noi""".split())

# Tên sản phẩm · hai câu nhắc hai sản phẩm khác nhau thì KHÔNG gom, dù trùng nhiều từ.
PRODUCTS = {"hera", "vega", "herahub", "vegahub", "herasight", "vegasight",
            "omnisight", "dualsight", "heralink", "aerotunnel", "skywatch"}


# Đồng nghĩa hẹp · quy về một từ để hai cách nói cùng chủ đề gặp nhau.
# Chỉ thêm cặp thật sự đồng nghĩa trong ngữ cảnh RtR; thêm bừa sẽ gom nhầm chủ đề.
CANON = {
    "mang": "payload", "nang": "payload", "taitrong": "payload", "chotai": "payload",
    "nits": "manhinh", "man": "manhinh", "hinh": "manhinh", "screen": "manhinh",
    "sangche": "patent", "bangsangche": "patent",
    "gia": "gia", "pricing": "gia",
    "nhietdo": "nhietdo", "nhiet": "nhietdo",
}


def content_tokens(q):
    out = set()
    for w in norm(q).split():
        w = CANON.get(w, w)
        if len(w) > 2 and w not in STOP:
            out.add(w)
    return out


def cluster(questions, min_size=2):
    """Gom câu hỏi cùng chủ đề · tiêu chí: chung >=2 từ nội dung, hoặc chung 1 từ hiếm.

    Bản cũ dùng tỷ lệ trùng >=0.6 nên chỉ gom câu gần trùng chữ, không gom paraphrase
    (QA TIP-13: ba cách hỏi 'nghỉ phép' không gom được). Bản này gom theo từ nội dung
    chung + lan truyền bắc cầu, có chốt chặn không gom hai câu hỏi về hai sản phẩm khác nhau.
    """
    items = [(q, content_tokens(q)) for q in questions]
    n = len(items)
    df = Counter(t for _, toks in items for t in toks)
    rare = {t for t, c in df.items() if c <= max(1, n * 0.15)}

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(n):
        for j in range(i + 1, n):
            ti, tj = items[i][1], items[j][1]
            if not ti or not tj:
                continue
            pi, pj = ti & PRODUCTS, tj & PRODUCTS
            if pi and pj and not (pi & pj):
                continue  # hỏi về hai sản phẩm khác nhau · chủ đề khác nhau
            shared = ti & tj
            if len(shared) >= 2 or (shared & rare):
                union(i, j)

    buckets = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(items[i][0])
    groups = sorted(buckets.values(), key=len, reverse=True)
    return [g for g in groups if len(g) >= min_size], [g[0] for g in groups if len(g) < min_size]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tuan", type=int, default=None, help="số thứ tự tuần pilot")
    ap.add_argument("--tu", type=str, default=None, help="ngày bắt đầu YYYY-MM-DD")
    ap.add_argument("--den", type=str, default=None, help="ngày kết thúc YYYY-MM-DD")
    a = ap.parse_args()

    end = datetime.fromisoformat(a.den + "T23:59:59") if a.den else datetime.now()
    start = datetime.fromisoformat(a.tu + "T00:00:00") if a.tu else end - timedelta(days=7)

    qa = [r for r in load(QA_LOG) if in_range(r, start, end)]
    gaps = [r for r in load(GAP_LOG) if in_range(r, start, end)]
    issues = [r for r in load(ISSUE_LOG) if in_range(r, start, end)]

    total = len(qa)
    live = sum(1 for r in qa if r.get("mode") == "LIVE")
    mock = total - live
    gap_q = len(gaps)
    answered = total - gap_q
    rate = round(100 * answered / total) if total else 0

    gap_groups, gap_singles = cluster([g.get("q", g.get("gap", "")) for g in gaps])
    top_groups, _ = cluster([r.get("q", "") for r in qa], min_size=2)

    L = []
    w = f"Tuần {a.tuan}" if a.tuan else "Tuần gần nhất"
    L.append(f"# Báo cáo pilot · {w} · {start:%d/%m} đến {end:%d/%m/%Y}\n")
    L.append("## Số máy đếm được\n")
    L.append("| Metric | Số | Ghi chú |")
    L.append("|---|---|---|")
    L.append(f"| Số câu hỏi trong tuần | {total} | LIVE {live} · MOCK {mock} |")
    L.append(f"| Tỷ lệ trả lời được từ gói | {rate} % | {answered}/{total} câu không rơi vào GAP |")
    L.append(f"| Số GAP mới | {gap_q} | gom thành {len(gap_groups)} nhóm lặp + {len(gap_singles)} câu lẻ |")
    L.append("| Số người dùng thực (unique) | | server pilot không định danh · đếm tay hoặc hỏi nhóm |")
    _rate = f"{100*len(issues)/total:.1f} %" if total else "—"
    L.append(f"| Số ca báo SAI | {len(issues)} | {_rate} số câu hỏi · ngưỡng chịu được dưới 2% |")
    L.append("| Fact nạp bổ sung trong tuần | | đếm entry mới trong l3_facts.yaml |\n")

    L.append("## GAP xếp theo tần suất · đây là lịch thu fact tuần sau\n")
    if gap_groups:
        for i, g in enumerate(gap_groups, 1):
            L.append(f"{i}. **({len(g)} lần)** {g[0]}")
            for variant in dict.fromkeys(v for v in g[1:] if v != g[0]):
                L.append(f"   - hỏi cách khác: {variant}")
    else:
        L.append("_Không có GAP lặp lại._")
    if gap_singles:
        L.append(f"\nCâu lẻ hỏi một lần ({len(gap_singles)}): " + " · ".join(gap_singles[:10]))
        if len(gap_singles) > 10:
            L.append(f"_(và {len(gap_singles)-10} câu nữa · xem gap_log.jsonl)_")
    L.append("")

    L.append("## Chủ đề được hỏi nhiều nhất · dấu hiệu use case thật\n")
    if top_groups:
        for i, g in enumerate(top_groups[:5], 1):
            L.append(f"{i}. ({len(g)} lần) {g[0]}")
        L.append("\n_Gate Phase 2 cần ít nhất 3 use case LẶP hàng tuần. Nhóm nào xuất hiện đủ 3 tuần liên tiếp thì tính là một use case._")
    else:
        L.append("_Chưa có chủ đề nào lặp lại._")
    L.append("")

    L.append("## Ca báo sai · phải trace về record gốc\n")
    if issues:
        for i, x in enumerate(issues, 1):
            L.append(f"{i}. **{x.get('q','(không rõ câu hỏi)')}**")
            if x.get("why"):
                L.append(f"   - người báo: {x['why']}")
            recs = x.get("records") or []
            L.append("   - record liên quan: " + (", ".join(recs) if recs
                     else "KHÔNG có mã record trong câu trả lời · đáng chú ý hơn cả nội dung sai"))
            L.append("   - [ ] đã trace nguồn · [ ] đã sửa kernel · [ ] đã báo lại người dùng")
    else:
        L.append("_Không có ca nào trong kỳ._ Nếu tuần nào cũng bằng 0 mà usage cao thì đáng ngờ: "
                 "có thể người dùng thấy sai nhưng ngại báo. Hỏi trực tiếp vài người.")
    L.append("")

    L.append("## Việc curator tuần sau\n")
    L.append("Với mỗi nhóm GAP ở trên: đi gặp ai, hỏi câu gì, nạp vào `kernel/registry/l3_facts.yaml`.\n")
    for i, g in enumerate(gap_groups[:5], 1):
        L.append(f"- [ ] GAP {i} ({g[0][:70]}) → hỏi: ______ → nạp record: ______")
    L.append("")
    L.append("Sau khi nạp fact: `python3 ../l3_pipeline/l3_export.py` → `python3 test_copilot.py` → restart server.\n")

    if not total:
        L.append("> Chưa có dữ liệu trong khoảng này. Server đã chạy chưa, nhóm đã được mời chưa?\n")

    report = "\n".join(L)
    print(report)
    OUTDIR.mkdir(exist_ok=True)
    name = f"tuan{a.tuan}" if a.tuan else f"{start:%Y%m%d}-{end:%Y%m%d}"
    out = OUTDIR / f"bao_cao_{name}.md"
    out.write_text(report, encoding="utf-8")
    print(f"\n[đã ghi {out}]")


if __name__ == "__main__":
    main()
