# TIP-013B · Group 1 — 32 kernel_ref facts RESOLVED (đề xuất chờ anh)

> **DRY-RUN** · phân tích từ snapshot kernel read-only (registry + 4 doc chiến
> lược đã stage) · **KHÔNG ghi kernel, KHÔNG activate.** Mỗi dòng là đề xuất
> kế thừa provenance từ record gốc mà chính kernel_ref trỏ tới — agent không tự
> quyết fact có đúng hay không, chỉ nối L3 wording về nguồn kernel đã khai.
> **Ngày:** 02/08/2026.

Group 1 của worklist (32 fact `kernel_ref` trong `l3_facts`) trước đây kẹt vì
thiếu record gốc. Nay đã stage `capabilities.yaml` (76 record HC/SC/OC),
`specs.yaml`, và 4 doc chiến lược (SPEC_CHANGELOG, CEO_STRATEGIC_STANCE,
POSITIONING_5CHAN, DOCTRINE_1PAGE). Kết quả resolve TRỌN 32:

## Tổng kết

| Nhóm | Số | Ý nghĩa | Hành động đề xuất |
|---|---:|---|---|
| → `verified_primary` | **5** | record gốc đã verified | **promote → ready** (38 → **43**) |
| → `claim` | 20 | record gốc mới là claim | gộp vào quyết định promotion (nhóm B của proposals) |
| → doc chiến lược | 6 | trỏ SPEC_CHANGELOG / CEO stance / positioning / doctrine | curator xác nhận wording khớp doc → provenance loại "strategic doctrine" |
| → chưa resolve | 1 | `L3R.K.005` trỏ toolkit `rtr-van-phong-nha-nuoc` | **reclassify/bỏ** — là tham chiếu quy trình, không phải nguồn fact |

## 5 fact lên thẳng ready (verified_primary)

| Fact | kernel_ref | 
|---|---|
| `L3R.2.005` | HC-056 · HC-057 · HC-058 |
| `L3R.2.013` | HC-042 |
| `L3R.2.027` | OC-001 |
| `L3R.3.030` | OC-001 |
| `L3R.K.006` | HC-042 |

**Đề xuất:** 5 fact này kế thừa provenance verified_primary từ record gốc → lên
ready ngay khi anh xác nhận L3 wording trung thành với record (đối chiếu sẵn có).

## 20 fact → claim (gộp promotion)

L3R.1.005/006/007/009/010/013/015/016/017/018/021, .2.014/028/029, .3.031,
.K.001/002/003/007. Record gốc (HC-001/002/012…/SC-015/020/OC-020) đang là
`claim` → các L3 này cũng là claim. Xử lý CÙNG 180 claim ở
`TIP-013B_CURATION_PROPOSALS.md` (promote / giữ-claim-kèm-caveat / loại).

## 6 fact → doc chiến lược (curator xác nhận)

`L3R.2.023`, `L3R.2.024` → SPEC_CHANGELOG (patent, FCC exemption);
`L3R.2.025`, `L3R.2.026` → CEO_STRATEGIC_STANCE / POSITIONING;
`L3R.2.032` → DOCTRINE_1PAGE; `L3R.K.004` → SPEC_CHANGELOG (legacy-tag).
Các doc đã stage — provenance loại "chủ trương chiến lược" (không phải spec
verified). **Đề xuất:** curator xác nhận L3 wording khớp doc → giữ tier
"strategic" + kèm caveat khi trả lời (đúng #2 của anh).

## 1 fact → reclassify

`L3R.K.005` trỏ toolkit `rtr-van-phong-nha-nuoc` (bộ văn phong) — đây là tham
chiếu QUY TRÌNH, không phải một sự thật công ty. **Đề xuất: loại khỏi SOT fact**
(hoặc chuyển sang tài liệu hướng dẫn, không phải fact registry).

## Ready sau khi áp Group 1

- Hiện tại: **38 ready**.
- + 5 verified_primary (Group 1) → **43** (chờ anh xác nhận wording).
- + 3 unit-drift (Proposals phần A) → **46**.
- 20 claim (Group 1) + 180 claim (B) = **200 claim** chờ quyết promotion — đây
  là đòn bẩy lớn nhất còn lại: 79 trong số đó đã có evidence_span (dễ promote).

## Việc chờ anh

1. Xác nhận 5 verified_primary Group 1 + 3 unit-drift → tôi áp, ready lên 46.
2. Hướng cho ~200 claim (đặc biệt 79 l3 có evidence_span).
3. `L3R.K.005`: đồng ý loại khỏi fact?

*Không mục nào được ghi vào kernel hay activate. Tất cả dry-run chờ anh.*
