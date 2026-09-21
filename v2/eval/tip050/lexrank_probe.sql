-- TIP-051.P · nhánh từ vựng có thiên vị bản ghi dài không?
-- `lexical_query` dựng truy vấn OR ("a | b | c"), còn `ts_rank_cd` mặc định
-- KHÔNG chuẩn hóa theo độ dài, nên một bản ghi dài trúng nhiều từ thường gặp
-- có thể vượt một bản ghi ngắn trúng đúng từ quyết định.
-- Câu thử: "Mật khẩu người dùng của RtR được băm bằng Argon2id phải không?"
-- Token sau chuẩn hóa và loại stopword của chính hệ thống.
\echo '--- A. xếp theo ts_rank_cd MẶC ĐỊNH (như production hôm nay) ---'
WITH q AS (
  SELECT to_tsquery('simple',
    'mat | khau | nguoi | dung | rtr | bam | bang | argon2id | phai') AS tsq
)
SELECT c.record_key,
       length(c.display_text)                                AS do_dai,
       round(ts_rank_cd(c.lexical, q.tsq)::numeric, 4)       AS mac_dinh,
       round(ts_rank_cd(c.lexical, q.tsq, 1)::numeric, 4)    AS chuan_hoa_log,
       round(ts_rank_cd(c.lexical, q.tsq, 2)::numeric, 6)    AS chuan_hoa_do_dai
FROM chunks c
JOIN active_search_generations ag ON ag.generation_id = c.generation_id
CROSS JOIN q
WHERE c.lifecycle = 'active' AND c.lexical @@ q.tsq
ORDER BY mac_dinh DESC
LIMIT 10;

\echo '--- B. xếp theo ts_rank_cd CÓ CHUẨN HÓA ĐỘ DÀI (cờ 2) ---'
WITH q AS (
  SELECT to_tsquery('simple',
    'mat | khau | nguoi | dung | rtr | bam | bang | argon2id | phai') AS tsq
)
SELECT c.record_key,
       length(c.display_text)                                AS do_dai,
       round(ts_rank_cd(c.lexical, q.tsq)::numeric, 4)       AS mac_dinh,
       round(ts_rank_cd(c.lexical, q.tsq, 2)::numeric, 6)    AS chuan_hoa_do_dai
FROM chunks c
JOIN active_search_generations ag ON ag.generation_id = c.generation_id
CROSS JOIN q
WHERE c.lifecycle = 'active' AND c.lexical @@ q.tsq
ORDER BY chuan_hoa_do_dai DESC
LIMIT 10;

\echo '--- C. bản ghi đích đứng hạng mấy theo từng cách xếp ---'
WITH q AS (
  SELECT to_tsquery('simple',
    'mat | khau | nguoi | dung | rtr | bam | bang | argon2id | phai') AS tsq
), scored AS (
  SELECT c.record_key,
         ts_rank_cd(c.lexical, q.tsq)    AS mac_dinh,
         ts_rank_cd(c.lexical, q.tsq, 2) AS chuan_hoa
  FROM chunks c
  JOIN active_search_generations ag ON ag.generation_id = c.generation_id
  CROSS JOIN q
  WHERE c.lifecycle = 'active' AND c.lexical @@ q.tsq
)
SELECT record_key,
       rank() OVER (ORDER BY mac_dinh DESC)  AS hang_mac_dinh,
       rank() OVER (ORDER BY chuan_hoa DESC) AS hang_chuan_hoa
FROM scored
WHERE record_key IN ('L3F.INF.014', 'L3F.2.039', 'L3F.REG.006', 'L3F.CERT.002');
