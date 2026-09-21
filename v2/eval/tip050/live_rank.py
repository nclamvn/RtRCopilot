"""TIP-052.P3 · dựng lại đúng bảng xếp hạng mà retrieval nhìn thấy.

Chạy BÊN TRONG container api:

    docker compose exec -T api python - < eval/tip050/live_rank.py

Vì sao cần: `bonus_probe` cho thấy hàm chấm điểm nay xếp L3F.INF.014 trên
L3F.2.039, nhưng đường chạy thật vẫn trả L3F.2.039. Nghĩa là hai bên đang nhìn
hai thứ khác nhau. Script này lấy ĐÚNG văn bản chunk trong generation đang hoạt
động, chấm bằng ĐÚNG hàm thật với profile dựng như retrieval dựng, rồi in bảng
theo thứ tự điểm. Sau bảng này không còn chỗ cho giả thuyết.
"""
import os

import psycopg

from rtr_copilot.rag.adapters import lexical_query, normalize_query
from rtr_copilot.rag.relevance import (
    candidate_relevance_score,
    mentioned_entities,
    profile_query,
)

CAU_HOI = "Mật khẩu người dùng của RtR được băm bằng Argon2id phải không?"
DSN = os.environ.get("POSTGRES_DSN", "")
if DSN.startswith("postgresql+"):
    DSN = "postgresql://" + DSN.split("://", 1)[1]

normalized = normalize_query(CAU_HOI)
tsq = lexical_query(normalized)
profile = profile_query(CAU_HOI, intent="lookup")

print(f"câu hỏi   : {CAU_HOI}")
print(f"tsquery   : {tsq}")
print(f"thực thể  : {profile.entities}")
print(f"từ khóa   : {profile.terms}\n")

SQL = """
SELECT c.record_key,
       c.display_text,
       ts_rank_cd(c.lexical, to_tsquery('simple', %s)) AS lex
FROM chunks c
JOIN active_search_generations ag ON ag.generation_id = c.generation_id
WHERE c.lifecycle = 'active'
  AND c.lexical @@ to_tsquery('simple', %s)
ORDER BY lex DESC
LIMIT 20;
"""

with psycopg.connect(DSN) as conn, conn.cursor() as cur:
    cur.execute(SQL, (tsq, tsq))
    rows = cur.fetchall()

print(f"{'bản ghi':26} {'lex':>6} {'điểm':>8}  nhắc thực thể")
ket_qua = []
for record_key, display_text, lex in rows:
    score = candidate_relevance_score(
        profile,
        text=str(display_text),
        record_key=str(record_key),
        base_score=1.0 / 61 + 1.0 / 61 + min(float(lex), 1.0) * 0.1,
        vector_score=0.20,
        min_vector_score=0.15,
        support_queries=(),
        semantic_floor=None,
    )
    ket_qua.append((record_key, float(lex), score, mentioned_entities(str(display_text), str(record_key))))

for record_key, lex, score, mentions in sorted(
    ket_qua, key=lambda r: (r[2] is None, -(r[2] or 0)),
):
    diem = "LOẠI" if score is None else f"{score:.3f}"
    print(f"{record_key:26} {lex:6.2f} {diem:>8}  {sorted(mentions) or 'không nhắc ai'}")

print("\nDòng đầu bảng này phải là bản ghi mà đường chạy thật trả về. Nếu không")
print("phải, phần lệch nằm ở tầng sau chấm điểm chứ không ở chấm điểm.")
for record_key, _, _, _ in ket_qua:
    if record_key == "L3F.INF.014":
        break
else:
    print("CẢNH BÁO: L3F.INF.014 không khớp tsquery, tức nó không nằm trong tập")
    print("ứng viên ngay từ SQL. Khi đó mọi thứ ở tầng chấm điểm đều vô nghĩa.")
