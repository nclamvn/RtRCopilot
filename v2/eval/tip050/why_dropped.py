"""TIP-052.P · vì sao một bản ghi bị loại, hỏi thẳng chính hàm đang chạy.

Chạy BÊN TRONG container api, nơi có đúng mã và đúng ontology đang phục vụ:

    docker compose exec -T api python - < eval/tip050/why_dropped.py

Không chạm DB, không mạng. Nó gọi thẳng `candidate_relevance_score` với cùng
bộ tham số mà retrieval truyền vào, cho hai câu hỏi chỉ khác nhau hai chữ và
hai bản ghi ứng viên, rồi in ra từng biến quyết định. Mục đích là biết bản ghi
bị loại ở tầng nào: cổng thực thể trong hàm này, hay sớm hơn ở cửa sổ ứng viên.
"""
from rtr_copilot.rag.adapters import lexical_query, normalize_query
from rtr_copilot.rag.relevance import (
    candidate_relevance_score,
    meaningful_terms,
    mentioned_entities,
    primary_entities,
    profile_query,
)

QUESTIONS = [
    ("KHÔNG có tên công ty", "Mật khẩu người dùng được băm bằng thuật toán nào?"),
    ("CÓ tên công ty", "Mật khẩu người dùng của RtR được băm bằng Argon2id phải không?"),
]

RECORDS = {
    "L3F.INF.014": (
        "Mật khẩu người dùng được băm bằng Argon2id với salt riêng cho từng "
        "người dùng."
    ),
    "L3F.2.039": (
        'RtR có gói "Em gửi anh Đông" v1.0 (14/07/2026) tại '
        "KnowledgeBase/Gui_Anh_Dong/: bộ công cụ hướng dẫn người ngoài dùng AI "
        "viết bản thảo và kiểm chứng dữ liệu."
    ),
}

for label, question in QUESTIONS:
    profile = profile_query(question, intent="lookup")
    print("=" * 74)
    print(f"{label}: {question}")
    print(f"  chuẩn hóa      : {normalize_query(question)}")
    print(f"  tsquery        : {lexical_query(normalize_query(question))}")
    print(f"  thực thể đích  : {profile.entities}")
    print(f"  từ quyết định  : {profile.terms}")
    for key, text in RECORDS.items():
        mentions = mentioned_entities(text, key)
        primary = primary_entities(text, key)
        text_terms = set(meaningful_terms(f"{key} {text}"))
        overlap = len(set(profile.terms) & text_terms)
        score = candidate_relevance_score(
            profile,
            text=text,
            record_key=key,
            base_score=0.1,
            vector_score=0.20,
            min_vector_score=0.15,
            support_queries=(),
            semantic_floor=None,
        )
        print(f"  --- {key}")
        print(f"      nhắc thực thể : {mentions or 'KHÔNG NHẮC AI'}")
        print(f"      thực thể chủ  : {primary or '-'}")
        print(f"      trúng từ      : {overlap}/{len(profile.terms)}")
        print(f"      điểm trả về   : {score if score is not None else 'None (BỊ LOẠI)'}")
print("=" * 74)
print("Đọc: nếu L3F.INF.014 ở câu thứ hai trả về một con số chứ không phải None")
print("thì cổng thực thể đã hết chặn, và chỗ loại nó nằm sớm hơn, ở cửa sổ ứng")
print("viên của truy vấn SQL. Nếu vẫn None thì xem dòng 'nhắc thực thể': bản vá")
print("TIP-052 chỉ cứu bản ghi KHÔNG nhắc ai, nên nhắc bất kỳ ai là không cứu.")
