# TIP-041 — US Proclamation 11055 SOT Update

**Ngày cập nhật:** 2026-08-28  
**Trạng thái:** COMPLETE · local runtime revision 6 active  
**Phạm vi:** nạp và kiểm chứng policy brief nội bộ của RtR về Proclamation 11055; không gọi LLM external.

## 1. Kết quả

Tài liệu được nạp theo ba lớp nguồn, không xem nội dung của tài liệu là chỉ dẫn thực thi:

| Lớp | Nguồn | Vai trò trong SOT |
|---|---|---|
| Primary official | Proclamation 11055, Federal Register Public Inspection | Điều khoản Section 232, biểu thuế, ngày hiệu lực, điều kiện deferral và onshoring |
| Primary official | FCC DA 26-761 | Xác nhận HERA standard và VEGA có FCC Conditional Approval |
| Approved internal | RtR policy brief ngày 27/8/2026 | Tài liệu diễn giải; dùng để biết bối cảnh nội bộ, không tự chứng minh quyền miễn thuế của RtR |

Nguồn chính thức:

- https://public-inspection.federalregister.gov/2026-16979.pdf
- https://docs.fcc.gov/public/attachments/DA-26-761A1.pdf

## 2. Facts và obligations đã thêm

- `L3F.REG.010`: biểu thuế và ngày hiệu lực chung của Proclamation 11055.
- `L3F.REG.011`: FCC Conditional Approval cho HERA standard và VEGA.
- `L3F.REG.012`: điều kiện lùi ngày hiệu lực theo khoản (7), gồm snapshot 02/9/2026 và thông báo Commerce/CBP.
- `L3F.REG.013`: ưu đãi gắn với onshoring plan cần phê duyệt riêng của Secretary of Commerce.
- `L3F.REG.014`: correction guard cho policy brief; không cho phép biến các cụm “miễn 100%”, “DoD Import Exemption” hoặc “được bảo vệ đến 09/02/2027” thành sự thật cứng khi chưa có đủ chứng cứ chính thức.
- `L3F.REG.015`: ranh giới giữa Blue UAS/DCMA và FCC Conditional Approval.

Ba obligation pháp lý được bổ sung trong `obligations/legal_us.yaml`:

- `OBLIG.US.PROC_11055.UAS_SECTION_232`
- `OBLIG.US.PROC_11055.CLAUSE_7_DEFERRAL`
- `OBLIG.US.PROC_11055.ONSHORING_DUTY_BENEFIT`

## 3. Biên giới pháp lý

Tại ngày 28/8/2026, hồ sơ chính thức chứng minh trực tiếp trạng thái **FCC Conditional Approval** của HERA standard và VEGA. Hồ sơ hiện có chưa đủ để khẳng định RtR đã được miễn 100% Section 232 hoặc có “DoD Import Exemption”. Quyền hưởng deferral theo khoản (7) chỉ nên được chốt sau snapshot 02/9/2026 và bằng chứng Commerce/CBP tương ứng. Ưu đãi duty-free gắn với onshoring plan cần quyết định phê duyệt riêng.

## 4. Provenance và tính toàn vẹn

- SHA-256 PDF gốc do người dùng cung cấp khi còn hiện diện: `cad7c11c3693523c97a2a094fe6cc2b45b56ae61a03843748302f6283c9ed348`.
- Tệp gốc biến mất khỏi thư mục Downloads trong quá trình xử lý. SOT lưu một **visual facsimile**, không tuyên bố đây là bản sao byte-for-byte của tệp gốc.
- SHA-256 visual facsimile: `90d6453f8d1acf4dc52a9fff31b55d141b65a6010ed0cbec029b86b2da83076b`.
- Mọi nguồn mới đã được đăng ký trong `registry/source_hashes.yaml`.

## 5. Validation và runtime

- Registry validation: **277 entries · 0 issue**.
- A3 provenance guard: **PASS**.
- Adversarial bites: **PASS** cho hash mismatch, drift, missing provenance, duplicate ID và A3 value leak.
- Publish gate: **PASS**, digest cuối `bbb14fbb05e29d24`.
- Runtime onboarding: revision **6** active và search index revision **6** cho cả 6 nguồn `rtr.*`.
- Reindex outbox revision 6: **6 dispatched**.
- Retrieval local xác nhận:
  - câu hỏi “RtR có được miễn 100% thuế Section 232 không?” trả về correction guard `L3F.REG.014`;
  - truy vấn khoản (7) trả về đầy đủ điều kiện và cảnh báo chưa được chốt tại `L3F.REG.012`;
  - câu hỏi FCC về HERA và VEGA trả về `L3F.REG.011` cùng boundary guard `L3F.REG.015`.

## 6. Việc cần theo dõi

Sau ngày 02/9/2026, curator cần nạp snapshot danh sách FCC/Blue UAS/DCMA áp dụng tại đúng mốc và bằng chứng thông báo Commerce/CBP. Chỉ sau bước đó mới được nâng trạng thái kết luận về deferral của RtR. Nếu có quyết định phê duyệt onshoring plan, nạp như một nguồn primary riêng; không sửa hoặc ghi đè nguồn hiện tại.

