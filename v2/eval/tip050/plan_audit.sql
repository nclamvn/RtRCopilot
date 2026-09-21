-- TIP-051 · đọc lại kế hoạch truy vấn của những lượt hỏi vừa chạy.
-- answer_runs.retrieval_config->'query_intelligence' là siêu dữ liệu audit có
-- sẵn từ TIP-024.7, không chứa văn bản câu hỏi, nên đọc nó không lộ gì thêm.
-- Dùng để phân biệt ba nguyên nhân: ràng buộc ontology chiếm chỗ ưu tiên,
-- mở rộng truy vấn làm loãng nhánh từ vựng, hay bộ lập kế hoạch không sẵn sàng.
SELECT
  left(m.sanitized_content, 44)                                        AS cau_hoi,
  r.state,
  r.retrieval_config->'query_intelligence'->>'intent'                  AS intent,
  r.retrieval_config->'query_intelligence'->>'planner_source'          AS planner,
  r.retrieval_config->'query_intelligence'->>'resolution_state'        AS resolution,
  r.retrieval_config->'query_intelligence'->>'entity_count'            AS ent,
  r.retrieval_config->'query_intelligence'->>'definition_record_count' AS def_n,
  r.retrieval_config->'query_intelligence'->>'profile_record_count'    AS prof_n,
  r.retrieval_config->'query_intelligence'->>'collection_record_count' AS coll_n,
  r.retrieval_config->'query_intelligence'->>'expansion_count'         AS exp_n,
  r.retrieval_config->'query_intelligence'->>'retrieval_query_count'   AS rq_n
FROM answer_runs r
JOIN messages m ON m.message_id = r.question_message_id
ORDER BY r.created_at DESC
LIMIT 24;
