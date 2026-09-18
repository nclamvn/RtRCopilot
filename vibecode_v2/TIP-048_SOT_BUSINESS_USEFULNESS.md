# TIP-048 · Nới kỷ luật SOT theo thực tế kinh doanh: thêm tầng thực hành, trục ngữ cảnh sử dụng, và nạp tầng hạ tầng CNTT

**Status:** PLANNED · chờ Homeowner phân xử 4 mục ở phần 0
**Date:** 18/09/2026
**Priority:** P0 (SOT đang làm chậm kinh doanh, không phải đang bảo vệ kinh doanh)
**Phụ thuộc:** TIP-046 (master spec sync, DONE), TIP-047 (hồ sơ NJ, PLANNED)
**Nguồn kích hoạt:** đối chiếu bản trả lời thủ công của team phần mềm với bản nháp dựng từ SOT cho bộ câu hỏi New Jersey. Trùng phán định thô 46,7%; team đánh Yes 20/30 lĩnh vực còn bản SOT chỉ 8/30.

## 1. Chẩn đoán: vì sao SOT trả lời thận trọng quá mức

Độ lệch không đến từ bất đồng về tình trạng thật của RtR. Nó đến từ hai nguyên nhân tách bạch được.

**Nguyên nhân A: thiếu vùng phủ.** Kernel hiện là SOT của sản phẩm và tuân thủ phần cứng. Không có một fact nào về hạ tầng CNTT. Tám lĩnh vực mà bản nháp để trống (3.0 nhân sự, 4.0 đào tạo, 6.0 quyền riêng tư, 7.0 tài sản, 10.0 truy cập, 19.0 quản lý thay đổi, 25.0 dự án, 30.0 ứng phó sự cố) đều là vùng kernel không có dữ liệu, trong khi team trả lời được ngay vì họ sống trong vùng đó. Đây là khoảng trống dữ liệu, sửa bằng cách nạp thêm.

**Nguyên nhân B: lỗi thiết kế trong luật provenance.** Đây mới là phần quan trọng.

Kernel hiện có một thang duy nhất: có nguồn sơ cấp thì thành `verified_primary` và dùng được; không có thì rơi xuống `claim`, bị luật A3 tước `value`, và adapter không bao giờ cho `ready`. Giữa hai cực đó không có gì.

Hệ quả: một việc RtR **làm thật hằng ngày** nhưng chưa có văn bản ký thì SOT coi như không tồn tại. Thu hồi tài khoản khi nhân viên nghỉ là thực hành có thật, kiểm chứng được bằng cách hỏi bất kỳ ai trong đội, nhưng vì chưa có chính sách ký nên SOT không nói được. Đó không phải thận trọng, đó là mù.

Thang hiện tại được thiết kế cho bối cảnh báo cáo nhà nước, nơi một con số sai là rủi ro pháp lý. Áp nguyên thang đó sang bối cảnh bán hàng và hợp tác thì biến SOT từ công cụ hỗ trợ thành vật cản.

## 2. Bốn phân xử cần Homeowner chốt

| # | Vấn đề | Đề xuất | Hệ quả nếu chốt |
|---|---|---|---|
| 1 | Kiến trúc sản phẩm thật: on-prem hay có cloud | Chốt theo mô tả của team (hybrid: GCS tại chỗ, relay và dữ liệu tài khoản trên AWS) | Nạp thành fact kiến trúc; sửa bản nháp NJ; mọi tài liệu sau dùng một mô tả duy nhất |
| 2 | Có chấp nhận tầng `attested_practice` (người có tên xác nhận là thực hành hiện hành, chưa cần văn bản) | Có | Mở khóa phần lớn 8 lĩnh vực đang trống, dùng được trong bán hàng và hồ sơ thầu |
| 3 | Có chấp nhận trục `use_class` (một fact khai báo dùng được ở ngữ cảnh nào) | Có | Nới cho bán hàng mà vẫn giữ sàn cứng cho văn bản cam đoan pháp lý |
| 4 | Danh mục "sàn cứng" không bao giờ nới | Theo bảng ở mục 4.3 | Giữ được bảo vệ ở đúng 5% chỗ mà sai một câu là mất hợp đồng |

## 3. Phương pháp mới

### 3.1 Thêm hai tầng provenance

Sửa `kernel/registry/phase_a/provenance_rules.py`.

| Tầng mới | Định nghĩa | Bắt buộc có | Giữ `value`? |
|---|---|---|---|
| `attested_practice` | Một người có tên xác nhận đây là thực hành đang chạy. Không cần văn bản. | `attested_by` (tên + vai trò), `attested_on` (ngày), `attest_scope` (phạm vi áp dụng) | Có |
| `roadmap_commitment` | Cam kết chưa đúng ở hiện tại, có chủ và có mốc. | `owner`, `target_date` | Có, nhưng luôn kèm nhãn thời điểm |

Hai tầng này **không** được suy tự động từ status. Chúng do người curate đặt, giống `approved_internal` hiện nay. Atomize không bao giờ tự gán.

Luật A3 giữ nguyên tinh thần: fact chưa xác minh không phơi `value` như sự thật cứng. Nhưng `attested_practice` **không phải** fact chưa xác minh. Nó đã được xác minh bằng lời chứng có người chịu trách nhiệm, chỉ là chưa có tài liệu. Đó là một loại bằng chứng khác, không phải bằng chứng yếu hơn về mặt tồn tại.

### 3.2 Thêm trục `use_class`

Đây là thay đổi cốt lõi. Hiện tại một fact chỉ có một câu hỏi: dùng được hay không. Thực tế kinh doanh cần câu hỏi khác: **dùng được ở đâu**.

Mỗi fact khai báo `use_class`, là tập con của ba ngữ cảnh lồng nhau:

```
attestation  ⊂  proposal  ⊂  sales
(cam đoan       (hồ sơ       (trao đổi năng lực,
 pháp lý)        thầu)        đối tác, bán hàng)
```

| Provenance | sales | proposal | attestation |
|---|---|---|---|
| `verified_primary`, `derived_from_verified` | Có | Có | Có |
| `approved_internal` | Có | Có | Có, nếu Homeowner ký |
| `attested_practice` | Có | Có, kèm nhãn "thực hành hiện hành, chưa văn bản hóa" | **Không** |
| `roadmap_commitment` | Có, kèm mốc | Có, kèm mốc và chủ | **Không** cho trạng thái hiện tại |
| `claim` | Không | Không | Không |

Nguyên tắc đọc bảng: fact dùng được cho `attestation` thì dùng được ở mọi nơi. Chiều ngược lại không đúng.

Ví dụ cụ thể, cùng một sự thật "RtR thu hồi quyền truy cập khi nhân viên nghỉ":
- Trong brief bán hàng và thảo luận đối tác: nói thẳng, vì có người xác nhận.
- Trong hồ sơ thầu: nói kèm nhãn thực hành chưa văn bản hóa.
- Trong bộ câu hỏi New Jersey (cam đoan có chữ ký): vẫn không được đánh Yes cho tới khi có chính sách ký, vì ô đó hỏi về chương trình văn bản hóa.

Một fact, ba cách dùng, không mâu thuẫn.

### 3.3 Sàn cứng không nới

Năm nhóm sau giữ nguyên yêu cầu bằng chứng tài liệu bất kể `use_class`, kể cả trong bán hàng:

1. **Trạng thái chứng nhận và phê duyệt.** ISO, SOC 2, FedRAMP, Blue UAS, FCC. Nói có khi chưa có là khai gian, không phải lạc quan.
2. **Trạng thái tuân thủ pháp lý.** NDAA, ITAR, kiểm soát xuất khẩu.
3. **Cam kết cư trú dữ liệu và quyền truy cập của nhân sự.** Đây là cam kết hợp đồng, sai là vi phạm.
4. **Số kỹ thuật sản phẩm.** Tải trọng, tầm bay, thời gian bay, TOPS. Vừa siết ở TIP-046, không nới lại. Phân xử 16/09 về tầm 10 km và 15 km giữ nguyên.
5. **Giá, chi phí, điều khoản thương mại.**

Lý do giữ: ở năm nhóm này, một câu sai không làm mất thể diện mà làm mất hợp đồng hoặc tạo rủi ro pháp lý. Nới ở 25 lĩnh vực còn lại đã đủ để SOT hữu ích.

### 3.4 Đổi cách dựng câu trả lời

Hiện tại: không có fact `ready` thì honest-null, trả lời "chưa có bằng chứng".

Mới: dựng câu trả lời ba lớp, chỉ honest-null khi cả ba lớp rỗng.

```
Lớp 1  Có văn bản      → nêu + dẫn nguồn
Lớp 2  Có thực hành    → nêu + nhãn "thực hành hiện hành, chưa văn bản hóa"
Lớp 3  Đã cam kết      → nêu mốc + chủ
                       ↓ cả ba rỗng
       honest-null      → "chưa có, và chưa có cam kết"
```

Đây vẫn là trung thực. Không bịa gì, mọi thứ đều có nhãn. Khác biệt là thay vì im lặng, hệ thống nói đủ những gì có thật.

## 4. Phase thi công

### Phase 1 · Sửa luật (Builder, 1 buổi)

| # | Việc | File |
|---|---|---|
| 1.1 | Thêm `attested_practice`, `roadmap_commitment` vào bảng provenance; cập nhật `keeps_value` để hai tầng này giữ `value`; `apply_a3_shape` bỏ qua chúng | `registry/phase_a/provenance_rules.py` |
| 1.2 | Thêm validate: `attested_practice` thiếu `attested_by`/`attested_on` là FAIL; `roadmap_commitment` thiếu `owner`/`target_date` là FAIL | `registry/validate.py` |
| 1.3 | Thêm cổng `use_class`: fact thuộc 5 nhóm sàn cứng mà `use_class` có `attestation` trong khi provenance là `attested_practice` hoặc `roadmap_commitment` thì FAIL | `registry/phase_a/provenance_guard.py` |
| 1.4 | Adapter: map hai tầng mới sang ready, tier soft, mang theo `use_class` vào record | `v2/eval/migrate/kernel_adapter.py` |
| 1.5 | Answer layer: dựng câu trả lời ba lớp; lọc theo `use_class` của ngữ cảnh đang hỏi | `v2/apps/backend/src/rtr_copilot/rag/answering.py` |

### Phase 2 · Nạp tầng hạ tầng CNTT (Builder + xác nhận của team phần mềm)

Nguồn: bản trả lời NJ của team phần mềm, là tài liệu có sẵn và đã viết kỹ. Mỗi mục thành fact với `attested_by` là người của team.

Nhóm fact dự kiến, khoảng 45 đến 55 fact:

- **Kiến trúc** (sau phân xử 1): cấu phần, AWS region chính và DR, ECS/EKS Multi-AZ, RDS, mô hình trách nhiệm chung.
- **Mã hóa**: AES-256 tại chỗ nghỉ qua KMS, TLS 1.2 trở lên, mã hóa đầu cuối luồng video và điều khiển, Argon2id băm mật khẩu, envelope encryption, xoay khóa hằng năm, khóa phiên không rời thiết bị.
- **Truy cập**: MFA bắt buộc, SAML 2.0 và OIDC, RBAC, mật khẩu tối thiểu 10 ký tự, khóa sau 5 lần sai, IP allowlisting, Session Manager cho truy cập quản trị.
- **Vòng đời phát triển**: Git và GitHub, pull request bắt buộc review, CI/CD, tách môi trường dev/staging/prod, Dependabot, SBOM, AWS Secrets Manager.
- **Giám sát**: CloudWatch, CloudTrail, lưu log 365 ngày, nguồn threat intel gồm CISA KEV, NVD, AWS Security Bulletins, GitHub Advisories.
- **Dự phòng**: backup RDS hằng ngày, point-in-time recovery, kiểm thử khôi phục nửa năm một lần, Multi-AZ, khôi phục sang region thứ hai, RPO và RTO.
- **Thực hành tổ chức** (`attested_practice`): onboarding và offboarding có tài liệu, NDA toàn bộ nhân sự, đào tạo nhận thức khi nhận việc, IR Plan và diễn tập bàn giấy 12 tháng một lần, Privacy Policy công bố tại rtrobotics.com/privacy.
- **Cam kết có mốc** (`roadmap_commitment`): MDM tập trung quý 1/2027, pen test độc lập trước go-live, đào tạo secure coding quý 4/2026, bảo hiểm trách nhiệm mạng trước khi triển khai cho khách.

### Phase 3 · Đóng các sai lệch đang mở

| # | Việc |
|---|---|
| 3.1 | Đóng cổng Blue UAS `L3F.REG.015`: hoặc nạp ảnh chụp danh sách DCMA để khẳng định cleared, hoặc hạ xuống "FCC Conditional Approval" và mô tả Blue UAS đúng trạng thái hồ sơ. Ba phiên bản hiện tại trong công ty không thể cùng tồn tại. |
| 3.2 | Nạp fact kiến trúc theo phân xử 1; đánh dấu mô tả "on-premises hoàn toàn" ngày 16/09 là sai lệch đã sửa, giữ trong ledger, không sửa im lặng. |
| 3.3 | Nạp danh mục chứng nhận vào dạng dùng được cho hồ sơ: ISO 9001, FCC DA 26-761, MIL-STD-810, DO-160G, FIPS 140-2 capable, ITAR, FAA Part 107, kèm đường dẫn bản scan. |

### Phase 4 · Ứng dụng và kiểm chứng

1. Onboard revision mới theo chu trình đã chứng minh ở TIP-046.
2. Sửa bản nháp NJ theo kiến trúc thật và luật mới; đối chiếu lại với bản team.
3. Chạy bộ eval ở mục 5.

## 5. Acceptance (oracle cam kết trước)

| Case | Câu hỏi hoặc phép thử | Kỳ vọng |
|---|---|---|
| BU-001 | "RtR có thu hồi quyền truy cập khi nhân viên nghỉ không?" (ngữ cảnh bán hàng) | Trả lời có, kèm nhãn thực hành chưa văn bản hóa. Fail nếu honest-null. |
| BU-002 | Cùng câu hỏi, ngữ cảnh `attestation` | Trả lời nêu rõ chưa có chính sách ký, kèm thực hành hiện có. Fail nếu đánh Yes trần. |
| BU-003 | "RtR có SOC 2 không?" ở mọi ngữ cảnh | Không. Fail nếu có bất kỳ cách diễn đạt nào ngụ ý có. |
| BU-004 | "Dữ liệu lưu ở đâu?" | Theo phân xử 1, nêu region cụ thể. Fail nếu còn nói không dùng cloud. |
| BU-005 | "HERA tải trọng bao nhiêu?" | 14 kg kèm 30 lb, y như sau TIP-046. Fail nếu luật mới làm trôi số sản phẩm. |
| BU-006 | "Bao giờ RtR có MDM?" | Quý 1/2027, kèm chủ. Fail nếu nói đã có. |
| BU-007 | Guard chạy trên registry sau khi nạp | 0 vi phạm cổng `use_class`; 0 fact `attested_practice` thiếu người xác nhận. |
| BU-008 | Đối chiếu lại 30 lĩnh vực NJ với bản team | Trùng phán định tăng từ 46,7% lên tối thiểu 80%. |

## 6. Rủi ro và cách chặn

| Rủi ro | Cách chặn |
|---|---|
| `attested_practice` thành con dấu cao su, ai cũng xác nhận mọi thứ | Bắt buộc tên người và ngày, kiểm được. Hạn 12 tháng, quá hạn tự rớt xuống `claim`. Homeowner lấy mẫu mỗi quý và yêu cầu chứng minh. |
| Fact `attested_practice` lọt vào văn bản cam đoan pháp lý | Cổng 1.3 có răng, chạy trong `check.sh`; adapter mang `use_class` vào record; answer layer lọc theo ngữ cảnh. Ba lớp chặn. |
| Nới lan sang số sản phẩm vừa siết ở TIP-046 | Nhóm 4 của sàn cứng. Case BU-005 canh. |
| Ngữ cảnh hỏi bị đoán sai, câu bán hàng bị áp luật attestation hoặc ngược lại | Mặc định là `proposal` (mức giữa). Ngữ cảnh `attestation` phải được nêu tường minh, không suy đoán. |

## 7. Nguyên tắc

- Nới ở chỗ sự thật có thật nhưng chưa có giấy. Không nới ở chỗ sự thật chưa có.
- Một fact, nhiều ngữ cảnh sử dụng. Không phải một thang đo cho mọi tình huống.
- Im lặng không phải là trung thực khi có điều đúng để nói. Trung thực là nói đủ và gắn nhãn đúng.
- Sàn cứng giữ ở đúng năm nhóm. Giữ ít chỗ để giữ được thật.
