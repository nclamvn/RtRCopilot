# TIP-013B · Curation Proposals (phần làm được ngay — chờ anh duyệt)

> **Trạng thái:** DRY-RUN · phân tích từ snapshot kernel read-only · **KHÔNG
> ghi lại kernel, KHÔNG activate.** Mỗi mục là ĐỀ XUẤT chờ anh xác nhận —
> agent không tự quyết nghĩa dữ liệu công ty.
> **Ngày:** 02/08/2026 · nguồn: adapter dry-run trên `kernel/registry`.

Đây là phần (c) — việc tôi hoàn tất được ngay mà không cần record gốc HC-/SC-/
OC- (đang chờ bridge để stage). Hai phần: 3 fact unit-drift (đề xuất chắc chắn)
và triage 180 fact `claim` để anh quyết promotion theo lô.

---

## Phần A — 3 fact unit-drift (sửa xong → 38 ready lên 41, thành `strict`)

Cả ba là trọng lượng HERA. Điểm chung: **giá trị số đúng**, chỉ nhãn `unit: lb`
là rác còn sót từ bug atomize — chính `raw_text` và `notes` của anh đã xác nhận
đơn vị đúng là **kg**. Đề xuất: đổi `unit` → `kg`. Bằng chứng nằm trong chính
fact, không cần nguồn ngoài.

| Fact id | key | value | unit hiện tại | Đề xuất | Bằng chứng (raw_text / notes của anh) |
|---|---|---:|---|---|---|
| `SPEC.HERA.WEIGHT.EMPTY` | Aircraft weight without battery | 9 | lb ❌ | **kg** | raw_text: "…without battery and payload: **9 kg**"; notes: "Manual fix (Lâm) · atomize unit bug (lb → kg)" |
| `SPEC.HERA.WEIGHT.TAKEOFF` | Takeoff weight, no payload | 16 | lb ❌ | **kg** | raw_text: "Takeoff weight… no payload: **16 kg**"; notes: "atomize unit bug (lb → kg)" |
| `SPEC.HERA.MTOW` | Maximum takeoff weight | 31 | lb ❌ | **kg** | raw_text: "MTOW (incl. max payload 15 kg): **31 kg**"; notes: "Correct per source = 31 kg… atomize regex bug extracted 15 lb" |

**Đề xuất xác nhận:** ba fact này đều `status: VERIFIED` với source rõ; sau khi
sửa `unit=kg` chúng có đủ verified provenance + span → lên `strict`, không cần
caveat. **Anh xác nhận "đúng, đổi sang kg" là tôi áp vào bản curated (vẫn
dry-run tới khi anh cho activate).**

> Lưu ý MTOW: notes của anh phân biệt rõ 31 kg (MTOW có payload 15 kg) vs 16 kg
> (empty MTOW) vs 14 kg (signature 1-4-14 = trọng lượng vác balo, KHÔNG phải
> MTOW). Đề xuất giữ nguyên value 31, chỉ sửa unit.

---

## Phần B — Triage 180 fact `claim` (quyết promotion theo lô)

`claim` = đã cào/ghi nhận nhưng chưa nâng thành fact công ty đã xác minh. Nâng
cấp là **quyết định curator** (fact này có đúng, đủ để coi là sự thật RtR
không?), nên tôi **không tự promote** — tôi chia thành nhóm hành động để anh
quyết nhanh theo lô thay vì duyệt 180 dòng lẻ.

**Phân bố:** capabilities 67 · l3_facts 79 · boms 22 · specs 8 · prices 1 ·
derived_costs 3. Phân loại: 158 internal · 22 restricted.

### Nhóm B1 — 79 claim l3 ĐÃ CÓ evidence_span (lô lớn nhất, dễ nhất)

Cả 79 claim trong `l3_facts` đã mang sẵn `evidence_span` — tức đã có văn bản
căn cứ, chỉ đang gắn nhãn `claim`. Ví dụ: `L3F.1.001` (spec HeraSight LR:
Sony ILX-LR1 61MP…), `L3F.1.008` (HeraLink→HeraHub từ 5/2026), `L3F.1.011`
(VEGA smart battery 50.4V 35000 mAh), `L3F.1.019` (kênh liên hệ chính thức).

**Đề xuất:** đây là ứng viên promotion sạch nhất. Ba đường xử lý theo mức chắc:
- **Promote → verified** nếu anh xác nhận evidence_span đủ mạnh (spec sản phẩm
  chính thức, đổi tên đã hiệu lực…) → lên `strict`/`soft`.
- **Giữ `claim` + hiện caveat** (đúng tính năng Part B) nếu là khẳng định định
  vị/chiến lược chưa muốn phơi như sự thật cứng → vẫn trả lời được, kèm dòng
  "cần kiểm chứng lại".
- **Loại** nếu lỗi thời (ví dụ tên/spec đã đổi).

Tôi đề xuất anh duyệt **theo lô con** (spec sản phẩm / naming / liên hệ / định
vị) thay vì từng dòng — tôi nhóm sẵn được nếu anh muốn.

### Nhóm B2 — 67 claim `capabilities` (cần bằng chứng hoặc là năng lực định vị)

Claim về năng lực. Chưa mang evidence_span trong lô này. **Đề xuất:** phần lớn
nên **giữ `claim` + caveat** cho tới khi gắn được nguồn — đúng tinh thần #2 của
anh (chấp nhận nhưng luôn kèm cảnh báo double-check). Cái nào có tài liệu chứng
minh thì promote riêng.

### Nhóm B3 — 22 claim `boms` (RESTRICTED — giá mua/nhà cung cấp)

Đây là 22 fact leader-only (giá vốn + nhà cung cấp). **Đề xuất:** giữ classification
`restricted` tuyệt đối; promotion (nếu có) chỉ trong vùng leader; không bao giờ
rơi xuống gói staff. Cần anh/curator xác nhận từng giá còn hiệu lực.

### Nhóm B4 — 12 claim còn lại (specs 8 · prices 1 · derived 3)

Nhỏ, xử lý lẻ: 8 spec-claim (đối chiếu specs.yaml VERIFIED), 1 price-claim
(xác nhận giá), 3 derived (giữ `claim` — là suy ra, không phải nguồn gốc).

---

## Việc chờ (cần bridge hoặc anh)

- **32 fact `kernel_ref`** (Group 1 worklist): cần stage record gốc HC-/SC-/OC-
  từ kernel (chờ bridge) HOẶC anh xác nhận L3 wording trung thành với kernel gốc.
  Khi bridge sống, tôi tự stage và hoàn tất dưới dạng đề xuất.
- **Áp các đề xuất đã duyệt** vào bản curated → chạy lại dry-run → số ready tăng
  dần. Vẫn không activate tới khi anh cấp H1/H2/H6 và bấm `--apply`.

## Anh cần làm gì bây giờ

Với Phần A: một câu "đổi 3 fact sang kg — OK" là tôi áp vào bản curated.
Với Phần B: chọn hướng cho từng nhóm (promote / giữ-claim-kèm-caveat / loại),
hoặc bảo tôi nhóm B1 thành các lô con để anh duyệt nhanh.

*Không mục nào ở đây được ghi vào kernel hay activate. Tất cả là đề xuất
dry-run chờ anh.*
