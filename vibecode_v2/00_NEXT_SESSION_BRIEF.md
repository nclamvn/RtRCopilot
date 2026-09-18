# Bản bàn giao phiên · Việc cần làm khi quay lại

**Chốt phiên:** 18/09/2026 · **Người viết:** Claude (Contractor) · **Đọc file này trước khi làm gì khác**

Nếu đây là phiên mới không còn ngữ cảnh: đọc mục 1 và 2, rồi chọn việc ở mục 3 theo thứ tự.

## 1. Trạng thái hiện tại

| Thành phần | Chốt ở | Ghi chú |
|---|---|---|
| `kernel/registry` | `e99624f` | Repo local, KHÔNG có remote, nên không push. `check.sh` PASS exit 0, 421 entry, 0 issue |
| `kernel` (cha) | `b401f7a` | Các file `_dist/`, `bim-pipeline/`, `energy-pipeline/` đang sửa là output pipeline khác của Homeowner, KHÔNG đụng vào |
| `KnowledgeBase/RtR_Copilot` | `3bdf25a` | Đã push `origin/main`, working tree sạch |
| Runtime SOT | **revision 10 active** | 6 nguồn `rtr.*`; l3_facts 189 chunk, specs 100 chunk; chunker `rtr-evidence-chunker/2` |
| Stack | docker compose | api map cổng **18000** (không phải 8000), web 3000, postgres/redis/minio/worker/clamav |

Kernel hiện có **ba nấc provenance** sau TIP-048, không còn hai:

```
verified_primary / approved_internal / derived_from_verified   -> dùng được mọi ngữ cảnh
attested_practice   (lời chứng có người đứng tên + ngày)       -> sales + proposal
roadmap_commitment  (cam kết có chủ + mốc)                     -> sales + proposal
claim / flagged / placeholder / legacy                          -> không dùng được
```

Sàn cứng năm nhóm KHÔNG nới, bất kể ngữ cảnh: chứng nhận, tuân thủ pháp lý, cư trú dữ liệu và quyền truy cập nhân sự, số kỹ thuật sản phẩm, giá và điều khoản thương mại.

## 2. Đọc trước khi làm

| File | Vì sao |
|---|---|
| `vibecode_v2/03_TASK_GRAPH.md` | Ledger, hàng TIP-046 đến 048.1 ở cuối |
| `vibecode_v2/TIP-048_SOT_BUSINESS_USEFULNESS.md` | Thiết kế ba nấc và trục `use_class` |
| `vibecode_v2/TIP-048_PHASE1_2_COMPLETION_REPORT.md` | Đã làm gì, deviation D1 đến D4 |
| `vibecode_v2/TIP-048.1_ADAPTER_SCHEMA_FIX.md` | Bài học test bằng model thật |
| `KnowledgeBase/NJ_Security_Questionnaire/QUYET_DINH_Cu_tru_du_lieu_va_nhan_su_VN.md` | Quyết định đang chờ, có sẵn câu chữ hai phương án |

## 3. Việc cần làm, theo thứ tự

### Việc 1 · Nghiệm thu TIP-048 (15 phút, không phụ thuộc gì)

TIP-048 chưa qua bước VERIFY của Vibecode. Mở `http://localhost:3000/ask`, hỏi 5 câu, dán kết quả cho Claude chấm:

1. RtR có thu hồi quyền truy cập khi nhân viên nghỉ việc không? → kỳ vọng CÓ, dẫn thực hành onboarding/offboarding (BU-001)
2. RtR có chứng nhận SOC 2 không? → kỳ vọng KHÔNG, không diễn đạt nào ngụ ý có (BU-003)
3. Dữ liệu của hệ thống lưu ở đâu? → kỳ vọng AWS us-east-1 và us-west-2 (BU-004)
4. HERA tải trọng tối đa bao nhiêu? → kỳ vọng 14 kg kèm 30 lb, canh xem TIP-048 có làm trôi số sản phẩm không (BU-005)
5. Bao giờ RtR có MDM? → kỳ vọng quý 1/2027, nêu như cam kết chứ không phải năng lực đang có (BU-006)

BU-002 CHƯA kiểm được, cần làm xong Việc 4 trước. Đạt 5/5 thì đổi TIP-048 trong ledger từ ◐ sang ✅.

### Việc 2 · Quyết định cư trú dữ liệu (5 phút đọc, mở khóa toàn bộ hồ sơ NJ)

Đọc bản quyết định ở mục 2. Đề xuất của Claude là **phương án A**: khai vị trí nhân sự Việt Nam ở câu II.7 và 10.5 kèm kiểm soát bù, giữ II.4 là Yes và II.9 như team đã viết.

Chọn A thì Claude nạp hai fact `approved_internal` vào kernel và sửa bản nháp. Chọn B thì ghi quyết định vào ledger kèm lý do, không nạp fact.

**Đây là nút cổ chai.** Mọi việc về hồ sơ NJ đứng sau nó.

### Việc 3 · Hoàn thiện hồ sơ New Jersey (sau Việc 2)

Ba bước, Claude làm được hết sau khi có quyết định:

1. **Dựng lại bản nháp PDF.** File hiện tại `KnowledgeBase/NJ_Security_Questionnaire/RtR_NJ_Security_Questionnaire_Response_DRAFT.pdf` đang viết "on-premises hoàn toàn", trong khi kernel đã ghi kiến trúc AWS. **Bản này đang sai so với SOT, đừng gửi đi.**
2. **Hợp nhất hai bản.** Lấy tầng hạ tầng từ bản team phần mềm, lấy danh mục chứng nhận và kỷ luật khai báo từ SOT. Bản team bỏ sót ISO 9001, FCC DA 26-761, MIL-STD-810, DO-160G, ITAR, FAA Part 107, và không dùng NDAA ở câu 27.0.
3. **Điền form gốc.** `ATTACHMENT 4` là AcroForm 220 trường, trong đó 30 dropdown mặc định "No". Kiểm kỹ không để sót ô mặc định ngoài ý muốn.

### Việc 4 · Bịt nợ kỹ thuật `use_class` (quan trọng nhất về mặt toàn vẹn)

Hôm nay `use_class` mới là nhãn mang trên record, **chưa phải bộ lọc**. Nghĩa là hàng rào ngăn một fact `attested_practice` lọt vào văn bản cam đoan pháp lý hiện do người giữ, không phải máy. Đây chính là thứ biện minh cho toàn bộ phần nới lỏng của TIP-048, nên để lâu là rủi ro.

Việc cần làm: dạy `rag/answering.py` nhận ngữ cảnh câu hỏi và lọc record theo `use_class` trong payload. Mặc định là `proposal` (mức giữa); ngữ cảnh `attestation` phải được nêu tường minh, không suy đoán. Xong thì chạy được BU-002.

Dữ liệu đã sẵn: mỗi record mang `value.use_class` và `value.sot_tier`.

### Việc 5 · Thu thập bằng chứng (chạy nền, không chặn ai)

| Việc | Nâng được gì |
|---|---|
| Bản scan ISO 9001, MIL-STD-810, DO-160G, FAA Part 107, ITAR, IP54 | `L3F.CERT.002` từ "chưa có bản scan" lên tầng có bằng chứng, dùng được trong văn bản cam đoan |
| Ảnh chụp danh sách DCMA Blue UAS (nếu tồn tại) | `L3F.RES.003` từ "chỉ FCC chứng minh được" lên khẳng định cleared |
| Tên kỹ sư chịu trách nhiệm | Thay `attested_by: "Team phần mềm RtR"` ở 52 fact `L3F.INF.*` bằng tên cá nhân, để lời chứng truy được tới người (deviation D1) |

### Việc 6 · Tồn đọng cũ, chưa gấp

- **TIP-040.1** worker poison-pill: hàng outbox mồ côi ném `ReindexError` nhưng không được đánh dấu, chặn đầu hàng đợi. Đã vá tay bằng SQL hai lần, chưa vá bằng code.
- **TIP-040.2** dọn dữ liệu test trong DB dev.
- 41 em-dash còn sót trong các fact `l3_facts` cũ, vi phạm quy tắc văn phong RtR (`OBLIG.STD.RTR_NO_EM_DASH`).
- Website ghi LS1 "120 dB ở 300 m", mâu thuẫn master (106 dB @3 m, tầm 400 m).
- Factsheet báo chí 14/07/2026 dùng số trước master (MTOW 30,5 kg, 15 km, 105 TOPS).

## 4. Cạm bẫy đã gặp, đừng lặp lại

| Bẫy | Cách tránh |
|---|---|
| **Dry-run bằng backend giả** làm lọt lỗi schema, chết ở Phase 4 | Bàn thử PHẢI dùng `models.py` và `package.py` thật của backend. `PackageRecord` ràng buộc `provenance_level`, `verification_state`, `fact_state` bằng `Literal`. Thêm giá trị mới là phải đổi schema và migration. |
| `git status` chạy qua device bridge để lại `.git/index.lock` mà bridge không xóa được | Kiểm trạng thái bằng lệnh không phải git (`ls`, `grep`). Nếu đã kẹt: `rm -f .git/index.lock .git/HEAD.lock` |
| `curl localhost:8000` trả về 000 | api map cổng **18000** |
| `device_bash` không với tới Docker của máy chủ | Mọi lệnh docker phải do Homeowner chạy trong terminal |
| `docker compose run` dùng image cũ | Thêm `--build`, hoặc `docker compose build api worker` trước |
| `validate.py` báo "Source missing" khi chạy ở cloud | Bình thường, vì mirror cloud không có `source_canonical/`. Trên máy Homeowner sẽ sạch. |
| Adapter chỉ nạp danh sách file cố định | Fact mới phải vào `l3_facts.yaml`, thêm file YAML mới sẽ không chảy qua pipeline |

## 5. Chu trình onboard, dùng lại nguyên văn

Đã chứng minh ba lần (revision 8, 9, 10). Lần sau dùng `--revision 11`.

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2
set -a; source .env; set +a
rm -rf /tmp/tipNNN && mkdir -p /tmp/tipNNN
docker compose run --rm --no-deps -v "$PWD/eval:/eval:ro" \
  -v /Users/os/RtR/kernel/registry:/kernel-registry:ro -v /tmp/tipNNN:/tmp/tipNNN \
  api python /eval/migrate/run_migration.py --kernel-root /kernel-registry \
  --out /tmp/tipNNN/packages --curated --revision 11 \
  --manifest-out /tmp/tipNNN/manifest.json --report-json /tmp/tipNNN/report.json | grep -E "final status|rtr\."
docker compose run --rm --no-deps -v /tmp/tipNNN:/tmp/tipNNN -e SOT_STAGING_ROOT=/tmp/tipNNN/packages \
  api python -m rtr_copilot.commands.onboard_batch --manifest /tmp/tipNNN/manifest.json \
  --apply --approve --report /tmp/tipNNN/ledger.json | grep -E '"activated_count"|"summary"'
sleep 90
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off \
 -c "select source_key, source_revision, lifecycle, chunk_count from search_generations where source_revision>=11 order by 1;"
```

Trước mọi lần onboard: `cd /Users/os/RtR/kernel/registry && bash check.sh` phải PASS exit 0.

## 6. Nếu chỉ có 30 phút

Làm Việc 1 (nghiệm thu, 15 phút) rồi Việc 2 (đọc và quyết, 5 phút). Hai việc đó đóng được TIP-048 và mở khóa toàn bộ hồ sơ NJ, là đường găng của phần còn lại.
