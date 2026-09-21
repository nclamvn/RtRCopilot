# TIP-048 + TIP-049 + TIP-050 · Runbook VERIFY gộp

**Ngày cam kết oracle:** 21/09/2026, trước khi chạy lượt nào.
**Người chạy:** Homeowner (chỉ máy Homeowner chạm được Docker; bridge không với tới).
**Mục đích:** một lượt chạy đóng ba gói đang treo VERIFY.

Oracle nằm trong `v2/eval/tip050/capture_use_class.py`, đã commit trước lượt chạy. Sửa kỳ vọng sau khi thấy kết quả là làm hỏng giá trị của phép kiểm; nếu kỳ vọng sai thì ghi deviation, đừng sửa lặng.

## 0. Điều kiện

Stack đang chạy, 6 nguồn `rtr.*` ở revision 11 (kết quả TIP-049 ngày 21/09). Nếu chưa chạy:

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2
docker compose up -d
curl -s localhost:18000/health/ready
```

## 1. Cổng tĩnh, chạy trước khi động vào stack

`.venv` trong `apps/backend` là venv dựng bên trong image Docker: `pyvenv.cfg` ghi `home = /usr/local/bin` và `bin/python` trỏ tới `/usr/local/bin/python3`, đường dẫn chỉ tồn tại trong container. Trên máy Homeowner nó là symlink gãy. Đường chạy đúng của repo này là `uv run`, như Makefile đang dùng ở target `eval` và `parity`.

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/backend
uv run pytest tests/test_tip050_use_class.py -q
uv run pytest -q
uv run mypy
uv run ruff check src tests
```

Chưa có `uv` thì `brew install uv`. Riêng bộ 16 test đơn vị chạy được không cần gì thêm, vì `use_class.py` không phụ thuộc thư viện ngoài nào:

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/backend
PYTHONPATH=src python3 -m pytest tests/test_tip050_use_class.py -q
```

| Cổng | Đạt khi |
|---|---|
| UC-001 | 16/16 xanh. Bộ này đã chạy xanh ngoài stack bằng chính module thật, nên đỏ ở đây nghĩa là môi trường lệch chứ không phải logic |
| UC-002 | Không hồi quy so với mốc 717 passed của TIP-038. Ghi con số thật vào Verify report |
| UC-003 | mypy không lỗi mới trên 4 file đã sửa |
| UC-004 | ruff sạch trên 4 file đã sửa |

Hỏng ở bước này thì dừng, đừng chạy tiếp bước 2: API chưa khởi động được với code mới thì mọi kết quả sau đều vô nghĩa.

## 2. Rebuild api và worker

Cổng `use_class` nằm trong tiến trình api. Code mới không vào nếu chỉ restart container cũ.

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2
docker compose build api worker && docker compose up -d api worker
curl -s localhost:18000/health/ready; echo
```

`health/ready` trả `{"ok":true,...}` là bằng chứng code mới nạp được: nối import sai thì tiến trình chết lúc khởi động. Container báo "Started" chưa nói lên điều đó.

## 3. Bàn thử tự động, 16 case

Bàn thử chỉ dùng thư viện chuẩn, không cần `uv` và không cần venv của backend.

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2
python3 eval/tip050/capture_use_class.py --base http://127.0.0.1:18000
```

Bảng in ra có PASS/FAIL từng case; bản ghi đầy đủ gồm câu trả lời và citation nằm ở `eval/tip050/use_class_capture.json`, đính kèm Verify report. Thoát 1 nghĩa là có case P0 hỏng.

### Bộ oracle

| Mã | Sev | Ngữ cảnh | Câu hỏi | Đạt khi |
|---|---|---|---|---|
| BU-001 | P0 | proposal | Thu hồi quyền khi nhân viên nghỉ việc | Trả lời được, nguồn là lời chứng thực hành |
| BU-002 | P0 | attestation | Cùng câu | Honest-null nêu rõ ngữ cảnh chứng thực và mã ghi nhận bị loại, KHÔNG trích nội dung |
| BU-003a/b | P0 | proposal, attestation | Có SOC 2 không | Không câu nào ngụ ý có. Registry không có fact nào nhắc SOC 2 |
| BU-004a | P0 | proposal | Dữ liệu lưu ở đâu | Nêu `us-east-1`, không còn nói không dùng cloud |
| BU-004b | P1 | attestation | Cùng câu | Honest-null. Xem phát hiện F1 bên dưới |
| BU-005 | P0 | proposal | HERA tải trọng tối đa | 14 kg, fail nếu 15 kg |
| BU-006 | P1 | proposal | Bao giờ có MDM | Đọc ra là cam kết tương lai, fail nếu nói đã có |
| UC-005 | P0 | mặc định | HERA tải trọng tối đa | Y như BU-005, chứng minh cổng mới không làm trôi hành vi cũ |
| UC-007 | P0 | attestation | HERA tải trọng tối đa | VẪN trả lời được, vì nguồn ở tầng đủ tư cách chứng thực |
| MS-009 | P0 | proposal | NETD HeraSight Standard | 40 mK |
| MS-010 | P0 | proposal | NETD HeraSight61 NDAA | 20 mK |
| MS-011 | P0 | proposal | VEGA RTK tích hợp hay tương thích | Cả hai, tùy yêu cầu khách |
| MS-012 | P1 | proposal | HERA có RTK không | Có hỗ trợ RTK |
| MS-013 | P0 | proposal | Quy ước phiên bản phần cứng | Chỉ dùng phiên bản lớn v1.0, v2.0 |
| MS-014 | P1 | attestation | Đã có scan ISO 9001 chưa | Nói CHƯA có scan |

UC-005 và UC-007 là hai case quan trọng nhất: chúng chứng minh cổng mới chặn đúng chỗ chứ không chặn bừa. UC-007 hỏng theo kiểu honest-null nghĩa là bộ suy luận tầng đang đọc sai và phải dừng gói.

## 4. Kiểm bằng mắt trên giao diện

Bàn thử đi đường API. Chạy thêm ba câu trên UI để chắc phần hiển thị không nói khác phần dữ liệu:

1. "HERA mang được tải trọng tối đa bao nhiêu?" phải ra 14 kg kèm 30 lb.
2. "HeraSight Standard NETD bao nhiêu?" phải ra 40 mK và không gom nhầm với bản NDAA.
3. "Quy ước đánh số phiên bản phần cứng của RtR?" phải ra v1.0 và v2.0.

Giao diện chưa có ô chọn ngữ cảnh, nên mọi câu hỏi trên UI chạy ở mặc định `proposal`. Đó là TIP-050.D1 còn treo.

## 5. Hai phát hiện cần Homeowner phân xử

**F1. Cư trú dữ liệu đang nằm ở tầng lời chứng.** Sàn cứng của TIP-048 liệt kê "cư trú dữ liệu và quyền truy cập của nhân sự" là nhóm 3, tức không được dùng tầng thực hành. Cổng sàn cứng trong `provenance_rules.py` bắt theo tiền tố mã (`SPEC.`, `PRICE.`, `COST.`, `BOM.`) và theo mẫu chữ (`data residency`, `cư trú dữ liệu`). `L3F.INF.002` nói hạ tầng đặt trên AWS vùng `us-east-1` nhưng không chứa cụm chữ nào trong mẫu, nên lọt cổng và đang ở tầng `attested_practice`. Cổng bắt theo chữ chứ không theo nghĩa.

Từ hôm nay TIP-050 vá được hệ quả: ở ngữ cảnh chứng thực, fact đó bị giữ lại. Nhưng nguyên nhân vẫn còn. Hai hướng, cần Homeowner chọn:

- Siết mẫu: thêm `us-east-1|aws region|vùng dữ liệu|trung tâm dữ liệu|data center|lưu trữ tại` vào `HARD_FLOOR_PATTERN`. Hệ quả: `L3F.INF.002` và vài fact hạ tầng khác sẽ bị chặn khỏi tầng thực hành, phải có tài liệu gốc mới dùng được, kể cả trong đề xuất.
- Giữ nguyên và dựa vào TIP-050: chấp nhận rằng ở đề xuất vẫn nói được region, chỉ cấm ở chứng thực.

Khuyến nghị của Builder: hướng thứ hai, kèm nâng `L3F.INF.002` lên `verified_primary` khi có ảnh chụp cấu hình AWS region. Cư trú dữ liệu là câu khách hỏi thường xuyên, chặn cứng ở cả đề xuất sẽ làm mất việc mà không tăng độ an toàn, vì đề xuất không phải cam kết có hiệu lực.

**F2. Không có fact nào nói RtR chưa có SOC 2.** BU-003 sẽ ra honest-null. Không sai, nhưng honest-null không phải câu trả lời tốt cho một câu khách hỏi thẳng. Đề nghị thêm `L3F.CERT.004` dạng sổ trạng thái phủ định: liệt kê những chứng nhận RtR CHƯA có và chưa theo đuổi (SOC 2, FedRAMP, StateRAMP, PCI-DSS), tầng `derived_from_verified` vì suy ra được từ chính sổ `L3F.CERT.001/002`. Nói "chưa có" là câu an toàn nhất trong mọi ngữ cảnh và hữu ích hơn im lặng.

## 6. Verdict

Verify report ghi ba phần riêng: TIP-048 (BU-001 đến BU-006), TIP-049 (MS-009 đến MS-014), TIP-050 (UC-001 đến UC-008). Một gói chỉ đóng khi mọi case P0 của gói đó PASS. P1 hỏng thì ghi deviation kèm REQ-ID, không chặn đóng gói.
