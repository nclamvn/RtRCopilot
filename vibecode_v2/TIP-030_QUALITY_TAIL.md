# TIP-030 · Quality Tail — Packet + Completion + Verify (gộp, 5 phase)

**Ngày:** 09/08/2026 · Nhánh `tip-030-quality-tail` · Homeowner chọn lane "đóng đuôi 4 case" sau TIP-029 (8/8 gate, verdict COMPANY-WIDE INTERNAL PILOT).
**Phương pháp:** mở kênh chẩn đoán → targeted run 4 case (rẻ) → fix theo bằng chứng → lặp. 5 vòng targeted, mỗi vòng thu hẹp đúng một van.

## Kết quả cuối

| Case | Kết cục | Van tìm ra |
|---|---|---|
| PRD-016 | ✅ FIXED (pass 3 vòng liên tiếp) | Prompt: bác tiền đề sai phải kèm giá trị đúng có cite |
| COM-008 | ✅ FIXED (pass 2 vòng, cite đúng oracle L3F.1.023) | (1) gate relevance chấm trên câu GỐC người dùng, không phải bản LLM rewrite; (2) meta-reply mode cho câu "khách hỏi X thì answer sao"; (3) checker locale "Vietnam"≡"Việt Nam" |
| SYS-007, MTH-004 | ◐ **CLASSIFIED → TIP-014** | Model tự phán `answerable:false` (decline — hành vi ĐÚNG) hoặc trả lời từ record sai (bị false-grounded flag chặn ĐÚNG). Gốc: retrieval thuần lexical không bắc cầu ngữ nghĩa ("tech stack"→L3F.4.011, "audit skill"→L3F.2.035). Giải pháp thiết kế sẵn = **real embedding (TIP-014 phase treo)**; 2 case này trở thành acceptance test của TIP-014 |

## Cải tiến cấu trúc kèm theo (giá trị vượt 4 case)

1. **Kênh chẩn đoán refusal** `decision_diagnostic` (env-gated `RAG_EXPOSE_DECISION_DIAGNOSTICS`, mặc định TẮT, có test khoá; nhãn cố định, không bao giờ là evidence).
2. **Phân loại đúng InsufficientEvidence**: decline nghiệp vụ không đánh oan circuit breaker/failure counters; metric `declined` riêng.
3. **Nhãn exhaustion mang class lỗi từng generator** (`provider_unavailable_declined` vs `_APIStatusError`...).
4. Relevance gate cuối chấm trên **câu gốc** (hợp đồng người dùng) — sửa lệch hermetic↔live.
5. Checker acceptance: locale-tolerant alpha terms (compact ≥4 ký tự).
6. Runner capture `decision_diagnostic` per-row.

## Gates

Hermetic: **586 passed / 127 skipped / 0 fail** · ruff 0 · mypy 0 (130 file). Targeted live: PRD-016 3/3 vòng, COM-008 2/2 vòng sau fix. Trust surface: production mặc định không đổi (test khoá).

## Disposition (Thầu)

- READY-with-classified: 2/4 fixed; 2/4 **không phải defect của lane này** — là dependency TIP-014 đã ghi sổ từ trước, nay có acceptance case + kênh chẩn đoán sẵn.
- Khuyến nghị giữ nguyên: thêm key provider thứ hai (resilience — decline một model có thể được model kia trả lời; run 5 xác nhận vẫn 1 generator).
- Re-cert full campaign: kỳ vọng 75/77 ≈ 97.4% (từ 73/77), 8/8 gate giữ nguyên.

*Đủ sàn audit: packet+completion+verify trong một tài liệu; số liệu 5 vòng nằm trong summary từng run trên nhánh.*
