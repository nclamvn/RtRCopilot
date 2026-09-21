"""TIP-052.P2 · thưởng-nhắc-tên-thực-thể có lấn át độ trùng chủ đề không?

Chạy BÊN TRONG container api:

    docker compose exec -T api python - < eval/tip050/bonus_probe.py

Kết quả why_dropped cho thấy cổng thực thể KHÔNG còn loại bản ghi sau TIP-052.
Nhưng L3F.2.039 chỉ trúng 3/9 từ mà đạt 1,047 điểm, trong khi L3F.INF.014 trúng
7/9 từ chỉ đạt 0,702. Chênh lệch đến từ hai khoản thưởng cho việc NHẮC ĐÚNG TÊN
thực thể: `coverage * 0.24` và `matched & primary` cộng 0.38. Tổng 0,62, xấp xỉ
toàn bộ trọng số dành cho độ trùng chủ đề.

Script này KHÔNG sửa mã. Nó chấm cùng một tập bằng hàm thật đang chạy, rồi chấm
lại bằng hai biến thể công thức tính ngay tại đây, để xem biến thể nào xếp đúng
cả ba câu hỏi, gồm một câu canh chiều ngược lại. Có số rồi mới sửa.
"""
from rtr_copilot.rag.relevance import (
    candidate_relevance_score,
    meaningful_terms,
    mentioned_entities,
    primary_entities,
    profile_query,
)

BASE = 0.1
VEC = 0.20
FLOOR = 0.15

CASES = [
    {
        "ten": "1. Câu kỹ thuật có nhắc tên công ty",
        "hoi": "Mật khẩu người dùng của RtR được băm bằng Argon2id phải không?",
        "intent": "lookup",
        "dung": "L3F.INF.014",
        "ung_vien": {
            "L3F.INF.014": "Mật khẩu người dùng được băm bằng Argon2id với salt "
                           "riêng cho từng người dùng.",
            "L3F.2.039": 'RtR có gói "Em gửi anh Đông" v1.0 (14/07/2026) tại '
                         "KnowledgeBase/Gui_Anh_Dong/: bộ công cụ hướng dẫn "
                         "người ngoài dùng AI viết bản thảo và kiểm chứng dữ liệu.",
        },
    },
    {
        "ten": "2. Câu sản phẩm, canh không làm hỏng cái đang đúng",
        "hoi": "HERA mang được tải trọng tối đa bao nhiêu?",
        "intent": "lookup",
        "dung": "SPEC.HERA.PAYLOAD.MAX",
        "ung_vien": {
            "SPEC.HERA.PAYLOAD.MAX": "Maximum payload capacity · HERA tải trọng "
                                     "tối đa, payload mang được bao nhiêu kg: 14 kg",
            "L3F.2.039": 'RtR có gói "Em gửi anh Đông" v1.0 tại KnowledgeBase/'
                         "Gui_Anh_Dong/: bộ công cụ hướng dẫn người ngoài dùng AI.",
        },
    },
    {
        "ten": "3. Câu định nghĩa, canh chiều ngược lại của việc nới",
        "hoi": "RtR là gì?",
        "intent": "definition",
        "dung": "L3F.ENT.001",
        "ung_vien": {
            "L3F.ENT.001": "Tên pháp nhân Việt Nam dùng trên văn bản chính thức: "
                           "CÔNG TY CỔ PHẦN REAL-TIME ROBOTICS VIỆT NAM (viết tắt "
                           "RTR). Mã số doanh nghiệp 0314718578.",
            "L3F.INF.014": "Mật khẩu người dùng được băm bằng Argon2id với salt "
                           "riêng cho từng người dùng.",
        },
    },
]


def variant(profile, text, key, *, scale):
    """Công thức hiện hành nhưng nhân hai khoản thưởng thực thể với `scale`.

    scale = 1.0 là y hệt bản đang chạy. scale nhỏ hơn 1 nghĩa là việc nhắc đúng
    tên thực thể vẫn có giá trị nhưng không còn lấn át độ trùng chủ đề. Ở đây
    `scale` được tính từ chính độ trùng chủ đề, nên một bản ghi vừa đúng tên vừa
    đúng chủ đề không mất gì.
    """
    mentions = mentioned_entities(text, key)
    primary = primary_entities(text, key)
    targets = set(profile.entities)
    text_terms = set(meaningful_terms(f"{key} {text}"))
    original_matches = len(set(profile.terms) & text_terms)
    term_overlap = original_matches / len(profile.terms) if profile.terms else 0.0
    adjustment = term_overlap * 0.62 + min(original_matches, 3) * 0.04
    if targets:
        matched = targets & mentions
        if not matched and original_matches < 2:
            return None
        factor = scale if scale is not None else term_overlap
        coverage = len(matched) / len(targets)
        adjustment += coverage * 0.24 * factor
        if matched & primary:
            adjustment += 0.38 * factor
        competing = len(mentions - targets)
        adjustment -= min(0.20, competing * 0.04)
    return BASE + adjustment


for case in CASES:
    profile = profile_query(case["hoi"], intent=case["intent"])
    print("=" * 74)
    print(f"{case['ten']}\n   hỏi: {case['hoi']}\n   đúng phải là: {case['dung']}")
    rows = []
    for key, text in case["ung_vien"].items():
        that = candidate_relevance_score(
            profile, text=text, record_key=key, base_score=BASE,
            vector_score=VEC, min_vector_score=FLOOR,
            support_queries=(), semantic_floor=None,
        )
        rows.append((
            key,
            that,
            variant(profile, text, key, scale=0.5),
            variant(profile, text, key, scale=None),
        ))
    print(f"   {'bản ghi':24} {'đang chạy':>10} {'thưởng x0,5':>12} {'thưởng theo chủ đề':>20}")
    for key, a, b, c in rows:
        fmt = lambda v: "LOẠI" if v is None else f"{v:.3f}"
        print(f"   {key:24} {fmt(a):>10} {fmt(b):>12} {fmt(c):>20}")
    for idx, nhan in ((1, "đang chạy"), (2, "thưởng x0,5"), (3, "thưởng theo chủ đề")):
        best = max(rows, key=lambda r: (r[idx] if r[idx] is not None else -1))[0]
        print(f"   -> {nhan}: chọn {best} " + ("ĐÚNG" if best == case["dung"] else "SAI"))
print("=" * 74)
print("Biến thể nào ĐÚNG cả ba case thì đó là công thức đáng đem vào mã.")
