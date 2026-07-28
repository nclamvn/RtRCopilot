# CHECKPOINT C2 · Phiếu duyệt cho Lâm (AI Officer / CEO-delegate)

**Ngày trình:** 2026-07-27 · **Chủ thầu:** Claude · **Gói:** 123 card L3 (TIP-1..4) + 11 dispute (9 mở + 2 đã xử) + 6 action item
> Cập nhật 2026-07-27: DISP.009/010 đã áp cách **tách-đôi** (xem LÔ 3) → thêm CAND.3.030/031, conflict còn 9.
**Trạng thái QA:** PASS (0 hard error · xem `QA_VERDICT_TIP1-4.md`) · **Mục tiêu C2:** ~30 phút, 5 lô, mỗi lô một quyết định.

> Cách dùng: mỗi lô có ô **QUYẾT ĐỊNH** — Lâm điền ✅ đồng ý / ✍️ sửa / ⏸ hoãn + ký tắt. Engine không tự resolve; mọi ca cần người quyết hoặc uỷ quyền.

---

## LÔ 1 · "Kernel thắng" theo lô (một chữ ký) — 3 dispute + 21 duplicate + 1 action

Nguyên tắc: kernel là SOT, nguồn cũ hơn/đã rename thua. Cả 3 đều truy về cùng một file stale.

| ID | Tranh chấp | Kernel (thắng) | Nguồn thua | Ngày |
|---|---|---|---|---|
| DISP.002 | Màn hình | HeraHub 1280×800 · 1800 nits (HC-017, chốt CEO 16/07) | HeraLink v2.0 1920×1200 · 1200 nits (doc thế hệ trước) | 2026-07-16 |
| DISP.003 | Độ sáng HeraHub | 1800 nits (HC-017) | 2000-nit (Company KB docx 18/05) | 2026-07-16 |
| DISP.004 | RMUS | Non-exclusive US reseller (SC-015 + D6 doctrine) | "exclusive" (Company KB docx 18/05) | 2026-06-30 |

- **+ 21 card duplicate**: trùng kernel, không mâu thuẫn → bỏ qua, không nạp lại.
- **+ ACT.004**: `RtR_Company_Knowledge_Base.docx` (18/05) tự nhận "Source of Truth" nhưng chứa cả 3 sai số trên (+ 33lb) → **đề xuất archive**, để kernel là SOT duy nhất. (Đây là "kho phân tán N+1" mà PRD cảnh báo — bằng chứng sống cho lý do dự án tồn tại.)

**QUYẾT ĐỊNH LÔ 1:** ☐ Đồng ý "kernel thắng" cả 3 + archive docx ☐ Sửa: ____________  ✍️ Ký: ______

---

## LÔ 2 · Gửi Engineering (một email 4 câu) — DISP.005/006/007 + ACT.005

4 spec HERA lệch giữa kernel và workbook bảo dưỡng (baseline DCMA). Nghi ngờ "rated vs demonstrated" hoặc "config VN vs US" — cần Engineering xác nhận, **không** engine tự chọn.

| ID | Field | Kernel | Workbook bảo dưỡng |
|---|---|---|---|
| DISP.005 | Kín nước/bụi | IP54 (HC-042 verified) | IP43 |
| DISP.006 | Tầm điều khiển | 15 km (HC-001) | 10 km |
| DISP.007 | Nhiệt độ thấp nhất | −30 °C validated (HC-040) | −20 °C |
| ACT.005 | Danh pháp + mốc bảo dưỡng | 1-4-14 hiện hành | còn "HERA 1-4-15" + mốc đang **PROPOSED** |

→ Draft email sẵn: **`C2_email_Engineering_draft.md`** (chỉ cần Lâm bấm gửi).

**QUYẾT ĐỊNH LÔ 2:** ☐ Đồng ý gửi email như draft ☐ Sửa nội dung ☐ Chỉ định người ký thay: ______  ✍️ Ký: ______

---

## LÔ 3 · Lâm tự xử (biết CEO trực tiếp) — DISP.008/009/010 + 8 card HOSO_CEO

| ID | Tranh chấp | value_a (kernel) | value_b (HOSO_CEO 6 đề án) | Đề xuất |
|---|---|---|---|---|
| DISP.008 | Học vị CEO | "PhD engineer + Fulbright, UC Berkeley" (OC-001) | "Tiến sĩ Kinh tế Phát triển, UC Berkeley" | Cùng trường, **khác ngành** → Lâm xác nhận ngành thật; nếu là Kinh tế Phát triển thì **sửa OC-001** (đang ghi "engineer"). Fact-sheet báo chí may chỉ ghi "Tiến sĩ tại UC Berkeley" (an toàn). |
| DISP.009 | Năm thành lập | 2014 (OC-001, entity US) | 2017 (pháp nhân VN) | ✅ **ĐÃ TÁCH** (2026-07-27): CAND.3.025="RtR VN 2017" (L2) + CAND.3.030="RtR US 2014" (L3, dup OC-001). Lâm chỉ cần duyệt có cho CAND.3.025 lên L3 không. |
| DISP.010 | Trụ sở | Lot I-4b-4.2 SHTP (nhà máy/VP) | 40/10 Khổng Tử (ĐKKD) | ✅ **ĐÃ TÁCH**: CAND.3.026="ĐKKD 40/10 Khổng Tử" (L2) + CAND.3.031="facility SHTP" (L3, dup OC-020). Lâm duyệt L2→L3 cho CAND.3.026. |

- **8 card HOSO_CEO** (CAND.3.022–029) hiện để **L2 + note "chờ Lâm xác nhận riêng"**. Sau khi Lâm xác nhận từng fact tiểu sử công khai được → hạ xuống L3. (CAND.3.025/026 đã tách nhưng vẫn giữ L2 tới khi Lâm ký.)

**QUYẾT ĐỊNH LÔ 3:** DISP.008 ngành TS = ____________ · sửa OC-001? ☐có ☐không · DISP.009/010 đã tách ✅ — cho CAND.3.025 & 026 lên L3? ☐có ☐không · HOSO card khác cho lên L3: ____________  ✍️ Ký: ______

---

## LÔ 4 · 🔴 KHẨN · Escalate CEO — DISP.011 (nằm trong hồ sơ nhà nước đã nộp)

**Vấn đề:** 6 đề án nhà nước (24 file BM) khẳng định **HERA "đã trên DCMA Blue UAS Cleared List"**. Trạng thái thật theo kernel:
- Signal mới nhất 22/07 (`SIG.MACRO.BLUE_UAS_LISTING_IN_PROGRESS`): **listing IN PROGRESS** dưới DoW Conditional Approval (FCC DA 26-616) — **chưa cleared**.
- SC-011 ("submission v8 FINAL") là của **VEGA**, không phải HERA; "submission final" ≠ "đã được list".

→ Sai **kép**: nhầm nền tảng (HERA↔VEGA) **và** nhầm trạng thái (in-progress↔cleared) — trong hồ sơ **đã nộp cơ quan nhà nước**. Đúng loại rủi ro client-risk audit.

→ Draft escalation sẵn: **`C2_escalation_DISP011_CEO_draft.md`**.

**QUYẾT ĐỊNH LÔ 4:** ☐ Chuyển CEO ngay (draft) ☐ Lâm tự xử lý đính chính ☐ Khác: ______  ✍️ Ký: ______

---

## LÔ 5 · Action items phân người — ACT.001/002/003/006

| ID | Việc | Người quyết đề xuất |
|---|---|---|
| ACT.001 | Cụm Control Tower 4 folder loạn danh tính (rtr-quanlyduan · rtr-ctl-fresh · rtr-pm/RtR-ControlTower · controltower rỗng) → chỉ định bản canonical | Owner Engineering |
| ACT.002 | rtr-mrp vs rtr-mrp-v2 nghi fork white-label VietERP → xác nhận quan hệ | Owner MRP |
| ACT.003 | 3 folder rỗng (rtr-twin · controltower · utm) → placeholder xoá được hay dự án sắp có | Lâm |
| ACT.006 | Vega Brochure ghi "33 lbs" copy-paste từ HERA (VEGA đúng 44 lb) → sửa cùng đợt brochure | Ethan Vo |

**QUYẾT ĐỊNH LÔ 5:** phân người từng ACT ở cột bên + hạn: ____________  ✍️ Ký: ______

---

## CÒN LẠI · 84 card `new` — duyệt theo domain

Không mâu thuẫn kernel, không nhạy cảm. Đã nhóm sẵn để duyệt nhanh: **product · process · company · system**. Không có card nào thiếu evidence/source (QA xác nhận).

**QUYẾT ĐỊNH:** ☐ Duyệt toàn bộ 82 vào L3 ☐ Loại/hạ tier các card: ____________  ✍️ Ký: ______

---

## DEFERRED (không chặn C2 — ghi để không quên)

- **DISP.001** (HeraSight 61T → "HeraSight LR"?) + **3 card unsure** naming → hỏi **Product team** một câu (liên quan HC-056 verify_action + 3 product line mới VegaSight/AeroTunnel/HeraSight LR chưa có trong registry — thấy trong DECISION_LOG SALES-01).
- **7 spec conflict** trong sheet `CONFLICTS_PENDING` của Master Canonical (flag từ 05/2026) → đề xuất một pass verify riêng với Engineering, ngoài phạm vi đợt này.
- Mốc bảo dưỡng vào L3 phải **giữ nhãn PROPOSED** cho tới khi Engineering ký (LÔ 2).

---

### TÓM TẮT CHỮ KÝ
LÔ1 ☐ · LÔ2 ☐ · LÔ3 ☐ · LÔ4 ☐ · LÔ5 ☐ · 82-new ☐ —— Lâm: __________ Ngày: 2026-07-__
