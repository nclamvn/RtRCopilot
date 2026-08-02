# TIP-013B · Khuyến nghị Chủ thầu — 101 claim + đường activate

> **Vai:** Tổng công trình sư (Contractor) · **Ngày:** 02/08/2026
> **Tính chất:** khuyến nghị có kiến giải, grounded từ nội dung thật · DRY-RUN.
> Quyết định cuối là của anh.

---

## Phần 1 — 101 claim: vì sao "giữ nguyên" là mặc định, và vì sao tôi ĐỔI khuyến nghị sau khi soi dữ liệu

### Vì sao ban đầu để mặc định giữ claim
`claim` = khẳng định đã cào/ghi nhận nhưng **chưa truy về nguồn sơ cấp**. Lời hứa
lõi của SOT là *mọi fact truy được về bằng chứng*. Promote một claim thành fact
mà chưa kiểm nguồn là phá đúng lời hứa đó. Nên mặc định an toàn — theo doctrine —
là **không tự động promote**. Đó là lý do tôi để 101 ở claim thay vì đẩy bừa.

### Vì sao giờ tôi đổi: 101 claim KHÔNG đồng nhất
Soi nội dung thật, 101 tách làm hai loại rất khác nhau về rủi ro:

| Loại | Số | Bản chất | Rủi ro nếu promote |
|---|---:|---|---|
| **Có nguồn tham chiếu** | 67 (capabilities) | Đều mang field `evidence`: brochure XPO26, KB sheet, DCMA submission, bảng sáng chế | Thấp — đây CHÍNH LÀ case #2 anh đã duyệt (có source note + caveat) |
| **Rủi ro thật** | 34 | 22 boms + 1 price (giá mua/nhà cung cấp) · 3 derived (chi phí/biên tính ra) · 8 spec interim (status INT, không raw_text) | Cao/không phù hợp — xem dưới |

**Kết luận:** "giữ cả 101" là quá thận trọng; "promote cả 101" là quá liều.
Đường đúng nằm giữa: **promote 67 có nguồn, giữ 34 rủi ro.**

### Khuyến nghị chi tiết

**① PROMOTE 67 capabilities → soft + caveat.** Kiến giải:
- Cả 67 đều đã có `evidence` là nguồn tài liệu (brochure/KB/DCMA/patent) — đúng
  y khuôn "verified-primary không span + chú thích nguồn + cờ double-check" mà
  anh đã chấp nhận ở quyết định #2. Không có gì mới về nguyên tắc; chỉ là áp
  nhất quán.
- Đây là **fact lõi về sản phẩm của chính RtR** (HERA, VEGA, HeraSight,
  OmniSight, DualSight…). Giữ chúng ở `claim` nghĩa là Copilot **không trả lời
  được câu hỏi cơ bản về sản phẩm công ty** — mất phần lớn giá trị, đổi lại gần
  như không được thêm an toàn (chúng đã có nguồn + sẽ luôn kèm caveat).
- Sau promote: ready **131 → ~198**. Đây là đòn bẩy lớn mà vẫn giữ kỷ luật.

**② GIỮ claim + caveat: 22 boms + 1 price (23 fact giá/chi phí).** Kiến giải:
- Đây là dữ liệu **nhạy cảm nhất** (leader-only: giá mua + tên nhà cung cấp).
- Và **trôi nhanh nhất**: một giá vốn cũ phơi như "sự thật" có thể gây sai lầm
  định giá/đàm phán thật — đúng loại "nguyên tắc chặt là chưa đủ" mà chính anh
  nói ở #2, nơi một dòng caveat KHÔNG đủ.
- Đề xuất: giữ claim; chỉ promote sau khi curator xác nhận từng giá còn hiệu
  lực, và chỉ trong vùng leader. Không promote theo lô.

**③ GIỮ claim: 3 derived** (BASE_BUILD_COST, MARGIN.HERA_VN, MARGIN.HERA_US).
Kiến giải: đây là **giá trị tính ra**, không phải fact sơ cấp. Chúng đổi khi
đầu vào đổi, nên **không bao giờ nên đóng băng thành SOT fact** — chúng thuộc
lớp derived, luôn tính lại, không khẳng định như sự thật bất biến.

**④ 8 spec interim (status INT, không raw_text):** giữ claim, TRỪ cái trùng một
spec đã VERIFIED (ví dụ `SPEC.HERA.MTOW.HC001` trùng MTOW ta vừa sửa). Kiến
giải: status INT + không có raw_text = chưa truy nguồn sơ cấp; an toàn là verify
ở lượt sau rồi mới promote.

### Con số nếu anh duyệt khuyến nghị
Ready **131 → ~198** (promote 67 caps). Còn ~34 giữ claim (23 giá/chi phí + 3
derived + 8 interim) + 26 curate. Tất cả 198 fact soft/strategic vẫn mang caveat.

---

## Phần 2 — Activate thật: khuyến nghị trình tự

Tôi không chạy `--apply` (không giữ credential thật). Nhưng đề xuất **cách vào**
để giảm rủi ro:

**Trình tự cấp đầu vào (rủi ro thấp → cao):**
1. **H6 secret trước** — đặt `.env.production`, đặc biệt `SOT_SIGNING_SECRET`
   (≥32 byte ngẫu nhiên, riêng). Boot guard sẽ từ chối nếu còn default → tự
   kiểm.
2. **H2 cert** — cert TLS thật + hostname; trỏ `INGRESS_TLS_MODE` sang file.
3. **H1 OIDC** — tenant Google Workspace thật (issuer/client id/secret,
   `DEV_OIDC_ENABLED=false`).

**Khuyến nghị lớn nhất: activate theo LÔ NHỎ trước, không đổ hết một lần.**
Kiến giải: đây là lần đầu dữ liệu thật đi qua cổng production. Nên:
- **Lô pilot:** activate 8 strict + ~10 soft tiêu biểu (HERA/VEGA core) trước.
- Chạy `make parity` + `make eval` trên lô này (embedding + provider thật) →
  xác nhận parity với V1 và leak = 0 trên dữ liệu thật.
- Nếu xanh → activate phần còn lại theo batch (capabilities, l3, strategic).
- Mỗi batch: dry-run sạch → `--apply --approve` dưới curator ký → kiểm ledger.

**Tôi chuẩn bị tới sát nút:** dựng manifest curated cho từng lô, chạy dry-run
tới khi sạch, để anh chỉ việc `--apply --approve`. Việc của anh là cấp H1/H2/H6,
curator ký attestation, và bấm nút.

---

## Việc chờ anh (mỗi cái một câu)
1. Duyệt **①** (promote 67 capabilities)? → tôi áp, ready lên ~198.
2. Đồng ý **②③④** (giữ 23 giá/chi phí + 3 derived + 8 interim ở claim)?
3. Khi có H1/H2/H6: tôi dựng lô pilot activate trước (8 strict + ~10 soft) hay
   anh muốn đổ full batch ngay?

*Không mục nào ở đây ghi vào kernel hay activate. Dry-run chờ anh.*
