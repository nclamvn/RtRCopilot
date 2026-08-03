# RtR Copilot V2 — Mô tả chi tiết ứng dụng và chức năng UI/UX

> **Loại tài liệu:** X-Ray sản phẩm và đặc tả UI/UX · **Ngày:** 02/08/2026
> **Phương pháp:** đọc trực tiếp mã nguồn thật dưới `v2/apps/web/src` (frontend) và
> `v2/apps/backend/src/rtr_copilot` (backend), đối chiếu ma trận 34/34 REQ.
> **Nguyên tắc:** chỉ mô tả cái mã thật sự làm. Không suy diễn, không tô hồng.

---

## 1. Ứng dụng này là gì

RtR Copilot V2 là một **hệ điều hành bằng chứng** (evidence operating system) dạng
web nội bộ cho Real-time Robotics. Toàn bộ trải nghiệm gói trong **một ứng dụng hợp
nhất**: một nhân viên có danh tính công ty đăng nhập một lần rồi Hỏi, Mở tệp, Tạo tài
liệu, Vận hành tri thức và Quản trị trong cùng một khung.

Lời hứa lõi định hình mọi màn hình: **mỗi câu trả lời chỉ dựa trên sự thật đã kiểm
chứng của RtR, mỗi khẳng định mở được về đúng trang, ô bảng, slide hoặc giây video
gốc. Thiếu bằng chứng thì hệ thống nói thẳng là chưa có và tự ghi thành khoảng trống
có người phụ trách**. Không bịa. Đây là điểm khiến sản phẩm khác một chatbot thường.

Về công nghệ, frontend là **Next.js App Router** (mọi trang là `"use client"` trừ hai
layout server và trang redirect gốc). Backend là **FastAPI + PostgreSQL 16 + pgvector
+ MinIO/S3 + Redis**. Trình duyệt **không bao giờ** gọi thẳng `/api/v1`. Mọi lời gọi
đi qua các **proxy same-origin `/api/*`** trong Next, mỗi proxy có allowlist họ đường
dẫn riêng, chặn path traversal, gắn `x-request-id` và chuyển tiếp cookie phiên.

Trạng thái tính năng: **33/34 REQ đã hiện thực cơ chế đầu-cuối có test gọi tên được,
1 REQ (REQ-020 truy hồi tệp đính kèm riêng của hội thoại) mới ở dạng an toàn honest-
null**. Giao diện đạt **WCAG 2.2 AA (axe 0 vi phạm trên 5 trang × 4 viewport × 2 ngôn
ngữ)**, keyboard-first, song ngữ Việt Anh, 73/73 kịch bản Playwright.

---

## 2. Kiến trúc nhìn từ giao diện

Dòng chảy một câu hỏi minh hoạ cả hệ:

Người dùng gõ câu hỏi ở màn **Hỏi** → Next proxy `/api/ask` chuyển sang backend
`rag/answering.py`. Backend chuẩn hoá câu hỏi, chặn ngân sách chi phí ngày, kiểm DLP
câu hỏi, rồi truy hồi lai: lọc metadata theo chính sách (ACL), lọc quyền từng chunk
(`policy.decide`), chấm điểm **lexical `ts_rank_cd` cộng vector cosine** rồi hợp nhất
theo reciprocal-rank fusion. Bằng chứng còn sống phải qua **lọc độ tin cậy**
(`require_verified`) và **DLP ngữ cảnh** trước khi tới nhà cung cấp trả lời. Câu trả
lời phải qua **cổng grounding** (`verify_grounding`): mỗi đơn vị sự thật phải có
citation, không được tự nhận "verified" trên nguồn claim hoặc hết hạn. Nếu không có
bằng chứng, hệ trả **honest-null** và ghi một **gap** vào hàng đợi quản trị có owner.
Kết quả về trình duyệt kèm citation, và các marker `[C1]` được nối tay tới **Evidence
Rail** để mở đúng vị trí gốc.

Bốn bề mặt khác (Tệp, Tài liệu, Vận hành tri thức, Quản trị) đều gắn vào cùng khung
này và **dùng chung một Evidence Rail**.

---

## 3. Hệ thống thiết kế hiện tại (ngôn ngữ thị giác thật)

Toàn bộ giao diện dùng **một stylesheet global** `src/app/styles.css`, chế độ
**tối duy nhất** (`color-scheme:dark`). Đây là diện mạo graphite hiện anh đang thấy.

**Token màu (`:root`):**

| Token | Giá trị | Vai trò |
|---|---|---|
| `--bg` | `#0d0f11` | Nền trang gần đen |
| `--panel` | `#15191c` | Mặt card graphite nhạt hơn |
| `--ink` | `#e8e6e3` | Chữ chính (tương phản ~15:1 trên nền) |
| `--muted` | `#92999f` | Chữ phụ, metadata |
| `--line` | `#2b3034` | Hairline 1px, dựng gần như toàn bộ khung |
| `--signal` | `#e56b46` | **Cam**, điểm nhấn duy nhất |
| `--locator` | `#76a8b3` | **Teal**, cho locator, checksum, mã monospace, chip SOT |
| `--focus` | `#f08a65` | Vòng focus cam |

**Cách dùng màu:** hệ xây từ **viền 1px** và **thanh nhấn trái `inset 3px 0`** cho
lựa chọn. Cam `--signal` là accent duy nhất, dùng cho eyebrow, gạch chân nav/tab đang
chọn, viền nút primary/danger, chip vùng RESEARCH, watermark DRAFT, bề mặt lỗi. Teal
`--locator` đánh dấu locator, checksum, mã, chip kiểu SOT, dòng chọn.

**Typography:** body `Helvetica Neue, Arial`. Tiêu đề hiển thị dùng **`Arial Narrow`**
cỡ lớn co giãn `clamp(30px,5vw,54px)` letter-spacing âm. Monospace `ui-monospace` cho
mã và metadata. Eyebrow chữ hoa cam 11px `letter-spacing:.18em`.

**Focus (WCAG):** mọi phần tử tương tác có vòng `outline:3px solid var(--focus);
outline-offset:3px`. Tương phản chữ ink trên nền ~15:1 vượt xa ngưỡng AA 4.5:1.

**Chuyển động:** `@media(prefers-reduced-motion:reduce)` tắt mọi transition và
scroll-behavior. Mọi trạng thái động đều có bản chữ tĩnh tương đương.

**Đáp ứng:** desktop dùng lưới `.shell` 64/232px và lưới ba cột catalog/surface/rail.
Tại ≤1100px, rail và panel biến thành **bottom sheet hoặc drawer** trượt lên, có nút
mở và scrim `rgba(0,0,0,.6)`. Tại ≤760px mọi thứ về một cột, nav thành drawer mobile.

*Ghi chú đánh giá: hệ này đúng kỷ luật a11y và bằng chứng, nhưng về thẩm mỹ đang ở
mức chức năng chứ chưa "dẫn đầu". Đây là cơ hội nâng cấp trải nghiệm có phạm vi rõ,
tách khỏi phần cơ chế đã vững.*

---

## 4. Khung ứng dụng hợp nhất (Unified Shell)

**Tệp:** `src/shell/AppShell.tsx`, `src/app/(shell)/layout.tsx`, `src/app/page.tsx`,
`src/app/layout.tsx`.

Mọi trang đặt dưới nhóm route `(shell)/` được bọc trong `<AppShell>`. Shell sở hữu
skip link, một topbar, nav trái và landmark `<main id="main">`. Mỗi trang chỉ render
**một** `<PageHeader>` là H1 duy nhất của trang.

**Redirect gốc:** `app/page.tsx` (server) chuyển `/` sang `/files` và **giữ nguyên
query string** để các deep-link locator TIP-008 (`?version=…&page=…`) vẫn mở đúng vị
trí. Đây là lý do khi mở app anh vào thẳng Tệp.

**Nav trái (`NAV_AREAS`):**

| Nhãn (vi/en) | Route | Vùng |
|---|---|---|
| Hỏi / Ask | `/ask` | ask |
| Tệp / Files | `/files` | files |
| Tài liệu / Documents | `/documents` | documents |
| Tri thức / Knowledge | `/knowledge-ops?view=research` | knowledge |
| Vận hành / Operations | `/knowledge-ops` | operations |
| Quản trị / Administration | `/admin` | admin |

**Chia nav D-011-01:** `activeArea()` cho biết Tri thức và Vận hành cùng trỏ tới trang
Knowledge-Ops nhưng khác `?view`. `?view=research|graduation` thuộc **Tri thức**, mọi
view khác thuộc **Vận hành**.

**Topbar:** nút menu (mobile), brand `RT` cộng tên shell, một affordance tìm kiếm
`shell-search` route tới `/ask` (hiện mã `/ask`), bộ chuyển ngôn ngữ **VI/EN**
(`role="group"`, mỗi nút `aria-pressed`), và khối danh tính (tên hoặc email + Đăng
xuất) hoặc link Đăng nhập khi chưa có phiên.

**Bàn phím và tiêu điểm:** skip link tới `#main`. **F6 / Shift+F6** xoay vòng mọi vùng
`[data-shell-region]` theo thứ tự nav ⇄ main ⇄ Evidence Rail, quy tắc vùng-trong-cùng-
thắng nên rail lồng trong main là một điểm dừng riêng chứ không thành bẫy. Sau mỗi lần
đổi pathname, tiêu điểm nhảy về `#main` (đổi query đơn thuần không cướp tiêu điểm).
Escape đóng drawer.

**Đa ngôn ngữ tại shell:** `setLocale` đổi ngôn ngữ tại chỗ không reload, ghi cookie
`rtr_locale` và cập nhật `document.documentElement.lang`.

---

## 5. Màn Hỏi (Ask) — trợ lý có căn cứ

**Route `/ask`** · `src/app/(shell)/ask/page.tsx` + `src/ask/*`. Đây là bề mặt trung
tâm, tiêu thụ API trả lời TIP-007 đã đóng băng qua proxy `/api/ask`.

**Bộ soạn câu hỏi.** Một ô nhập câu hỏi, nút gửi. Có **kiểm soát phạm vi**: mặc định
**SOT công ty**, cộng tuỳ chọn **Kèm vùng nghiên cứu** bị chặn bởi capability
`research/scope` (không có quyền thì tuỳ chọn hiện trạng thái bị từ chối). Có **picker
giới hạn trong tệp**: chọn một tệp trong catalog đã lọc ACL, câu hỏi sẽ chỉ truy hồi
trong `filters.source_key` của tệp đó. Bằng chứng ngoài phạm vi chính sách không bao
giờ xuất hiện dù chọn cách nào.

**Câu trả lời có căn cứ.** `AnswerText` tách văn bản, mỗi marker `[C1]` render thành
một `<button>` nối tới rail. Bấm marker gọi `openCitation`: mở Evidence Rail, đặt
`activeKey`, và focus đúng entry trên khung hình kế tiếp. Câu trả lời hiển thị y theo
nhãn backend (zone_label, tier, grounding).

**Honest-null là công dân hạng nhất.** Khi không có bằng chứng đủ tin cậy, màn hiện
khối **"Chưa có bằng chứng"**, ghi rõ **id khoảng trống** đã ghi nhận cùng **trạng
thái** (open…), và một link **Mở trong Vận hành tri thức** cho curator. Hệ tuyệt đối
không để model tự trả lời khi rỗng bằng chứng.

**Dòng caveat độ tin cậy.** Với câu trả lời dựa trên fact **soft** (nguồn đã kiểm
chứng nhưng chưa có span nguyên văn), một dòng nhỏ `role="note"` hiện ra: *"Một số căn
cứ chưa có trích dẫn nguyên văn, vui lòng kiểm chứng lại"* (tiếng Anh qua i18n). Dòng
này **chỉ** xuất hiện ở câu soft, đúng khuôn "AI có thể sai" dưới khung soạn, không
hiện tràn lan. Câu chỉ dựa fact strict thì không có caveat.

**Lịch sử hội thoại.** Panel liệt kê các hội thoại của chính người dùng (id, mốc thời
gian, digest câu hỏi đầu). Mở lại được, và id hội thoại **khôi phục qua URL**
(`?conversation=`), không đụng localStorage.

**Trạng thái.** idle, đang hỏi (`aria-live`), thành công, honest-null, và các trạng
thái từ chối hoặc lỗi có mã điển hình.

**Gọi backend:** `/api/ask` (hỏi, hội thoại) và `/api/governance` cho
`research/scope`, `research/search`, `gaps/{id}`.

---

## 6. Evidence Rail (thanh bằng chứng dùng chung)

**Tệp:** `src/rail/EvidenceRail.tsx`, `ZoneChip.tsx`, `contracts.ts`. Một component
duy nhất dùng chung cho cả bốn bề mặt Hỏi, Tệp, Tài liệu, Vận hành.

`<aside id="evidence-rail" data-shell-region>` mang nhãn **"Bằng chứng & xuất xứ"**.
Vì có `data-shell-region` nên nó **tham gia vòng F6**. Dưới ~1100px nó thành bottom
sheet trượt lên, trang chủ quản cung cấp nút mở, scrim và Escape.

**Mỗi entry** là một `<article>` có id để `focusRailEntry` nhắm tới, `aria-current`
khi đang chọn. Đầu entry: `ZoneChip`, mã `[marker]`, `Tier`, chip `DLP` khi bị che,
và nhãn nguồn. Sau đó là snippet, rồi **`EntryFacts`** (một `<dl>` liệt kê: Vùng tin
cậy, Căn cứ grounded hay research_supported, Tier, Nguồn `label · key · bản n`, Bản
ghi, Phiên bản, các Checksum bản ghi/bằng chứng/nội dung rút gọn 16 ký tự có title đủ,
Xuất xứ, Kiểm chứng, Độ tươi, Đối chiếu, Trạng thái chính sách). Cuối cùng là locator:
nếu có định vị sâu thì một `<Link>` **"Mở đúng vị trí — {locatorText}"** dựng URL
`/files?version=…&<locator>`, ngược lại hiện "Không có định vị sâu".

**ZoneChip** chỉ render khi zone đúng là `sot|research|private`, luôn lấy từ
`zone_label` của máy chủ. Client không bao giờ tự đoán vùng. Lớp `contracts.ts` chốt
cổng vùng ở rìa client: một citation gắn nhãn lạ sẽ **ném lỗi `zone_label_forged`**,
đồng thời kiểm marker `^C\d{1,3}$`, UUID, checksum HEX64, tiers, corroboration.

---

## 7. Màn Tệp (Files) — không gian tệp an toàn

**Route `/files`** · `src/app/(shell)/files/page.tsx` + `src/files/*`.

**Catalog và lọc.** Danh sách tệp đã lọc ACL, có **facet loại**: Tất cả, Ảnh, PDF,
DOCX, XLSX, PPTX, Video, Audio. Có ô tìm theo tên tệp hoặc tài liệu.

**Trình xem an toàn (safe rendition).** Bảy họ viewer: ảnh, PDF, Office (DOCX/XLSX/
PPTX), video, audio. Chỉ **bản xem đã qua kiểm tra** hiện ra, ảnh đã loại metadata,
PDF trong iframe có title, sóng âm cho audio. Bản gốc tải xuống đi qua đường ủy quyền
riêng.

**Tải lên.** Chọn đích lưu (target có phân loại), kéo thả tệp, thanh tiến trình, trạng
thái và nút thử lại khi lỗi. Upload đi vào quarantine, sniff MIME, quét ClamAV fail-
closed, dedupe sha256, chặn theo quota. Không bao giờ tự thành SOT.

**Deep locator.** URL mang `rtr.locator.v1` (version, page, sheet, cell, slide,
start_ms timecode). Đây là hợp đồng để một citation ở Hỏi mở đúng trang, ô bảng, slide
hoặc giây video ngay trong Tệp.

**Gọi backend:** proxy `/api/files` stream cả rendition lẫn download, có header
`range`, `content-range`, `content-disposition`, `etag`.

---

## 8. Màn Tài liệu (Documents) — Document Operating System

**Route `/documents`** · `src/app/(shell)/documents/page.tsx`. Eyebrow **"Document
Operating System"**, title **"Tài liệu"**.

**Sổ đăng ký mẫu (trái).** Danh sách **mẫu đã duyệt**, mỗi mẫu hiện `{format} · V{bản}`,
tên hiển thị, `{category} · {document_class}`. Chọn mẫu ghi URL `?template={version_id}`
và nạp schema.

**Bàn lắp ráp (giữa).** Form có **một ô nhập cho mỗi binding người dùng**, binding bắt
buộc đánh dấu `*`. Hai hành động: **Kiểm tra dữ liệu** (`bind()`) và **Tạo bản xem**
(`renderDocument()`). Kết quả bind `role="status"`: hợp lệ thì "Dữ liệu hợp lệ và đã
khóa nguồn", không hợp lệ thì liệt kê "Thiếu … · Chặn …".

**Trộn dữ liệu (data-merge).** Bind chia field thành **do người nhập**, **fact SOT
khóa cứng** (`locked_fact`) và **derived**. Các fact SOT khóa cứng được ánh xạ thành
entry của Evidence Rail (mang record_key, checksum, provenance, freshness), nên tài
liệu chính thức truy được về đúng nguồn.

**Render tất định và bản xem an toàn.** `render` gửi `idempotency_key` ngẫu nhiên, poll
job mỗi 650ms, có thanh `<progress>` `aria-live`. Khi xong, dùng **chính `FileViewer`
như màn Tệp** để xem an toàn. Nếu tài liệu chưa phát hành và không phải hạng internal,
hiện **watermark "DRAFT · CHƯA PHÁT HÀNH"** xoay −18°, nền chip riêng đạt tương phản
AC-10.

**Duyệt, phát hành, thu hồi (chân rail).** Một timeline trạng thái theo vòng đời với
hàng hành động đổi theo state: `draft` → **Gửi duyệt**, `in_review` → **Duyệt** hoặc
**Từ chối** (kèm lý do), `approved` → **Phát hành**, `issued` → **Thu hồi**. Có tách
biệt nhiệm vụ (SoD) từ policy. Kèm **Lịch sử và so sánh** liệt kê từng phiên bản
`V{n} · {lifecycle}`, checksum, tham số đổi, SOT đổi.

**Gọi backend:** `/api/document-os` cho templates, bind, render, vòng đời; `/api/files`
cho viewer-manifest bản xem.

---

## 9. Màn Vận hành tri thức (Knowledge-Ops) — bàn làm việc của curator

**Route `/knowledge-ops` với `?view=…`** · `src/app/(shell)/knowledge-ops/page.tsx`,
`zone.tsx`, `src/governance/*`. Đây là nơi bảy bề mặt bản thiết kế (SOT, Gaps, Audit,
Freshness, Conflict, Owner-review, Research) hợp nhất thành các view.

**Sổ hàng đợi (trái).** Một dòng **Bảng điều hành** cộng sáu dòng tính từ dashboard,
mỗi dòng có `ZoneChip`, nhãn, `<output>` đếm sống và badge SLA cam khi cần:

| view | nhãn | đếm | badge |
|---|---|---|---|
| gaps | Khoảng trống | `gap_flow.open_total` | `{overdue} quá hạn SLA` |
| freshness | Độ tươi | `freshness.total` | `{expired} đã hết hạn` |
| conflict | Xung đột | `conflict.total` | `{disputed} đang tranh chấp` |
| owner-review | Rà soát định kỳ | `owner_review.total` | `{overdue} quá hạn` |
| research | Gói nghiên cứu | Σ `packages_by_state` | `{rejected} bị từ chối` |
| graduation | Nâng cấp | `graduation.proposed` | `{submitted} tại cổng` |

**Bảng điều hành sống.** Các tile coverage/freshness/gap_flow/conflict/owner_review
được **tính lại mỗi lần gọi dưới phạm vi của người xem**, không có snapshot lưu sẵn
phục vụ số nào, và hàng bị từ chối không bao giờ được đếm.

**Trạng thái URL `?view=`:** `dashboard | gaps | freshness | conflict | owner-review
| research | graduation`, cộng các id UUID hợp lệ `?gap= ?package= ?record= ?proposal=`
và bộ lọc gap `?state= ?priority=`. `popstate` khôi phục. Đây chính là nguồn của chia
nav Tri thức và Vận hành.

**Bề mặt làm việc.** `tabIndex=0` để vùng cuộn nhận tiêu điểm bàn phím. Đầu bề mặt có
`notice` (`role="status"`) và `actionError` (`role="alert"`). Các hành động gồm triage,
assign, answer, decline khoảng trống; assign và complete hàng freshness/conflict/owner-
review; import gói nghiên cứu và **đề xuất nâng cấp qua cổng graduation** không bao giờ
tự kích hoạt. Có **picker** dạng combobox WAI-ARIA đầy đủ để chọn subject hoặc record.

**Gọi backend:** toàn bộ qua `/api/governance` (dashboard, gaps, queues, research,
graduation, pickers).

---

## 10. Màn Quản trị (Admin)

**Route `/admin`** · `src/app/(shell)/admin/page.tsx`. Hiện là **placeholder, chưa có
giao diện quản trị**. Trang render `PageHeader` (title "Quản trị") và một card liệt kê
năm bề mặt API quản trị đã có ở backend nhưng chưa có UI tiêu thụ:

- Nguồn nghiên cứu · `/api/v1/admin/research-sources`
- Thiết lập quản trị (SLA, ngưỡng) · `/api/v1/admin/settings`
- Ghi đè ưu tiên khoảng trống · `/api/v1/admin/gaps/{gap_id}/priority`
- Tài khoản chủ thể và vai trò · `/api/v1/admin/subjects`
- Sức khỏe job nền · `/api/v1/admin/jobs/health`

Đây là một **khoảng cách UI có tên**: backend có, mặt trước chưa dựng.

---

## 11. Xuyên suốt — đa ngôn ngữ, truy cập, trạng thái, bảo mật proxy

**Đa ngôn ngữ.** Tiếng **Việt là mặc định và là nguồn chân lý**. Tập khóa `vi` định
nghĩa kiểu `MessageKey`, `en` bị **ép biên dịch** phải đủ mọi khóa, thiếu hoặc thừa là
lỗi compile, thêm test parity lúc chạy. Chỉ đổi chuỗi và locale `Intl`, layout giữ
nguyên hai ngôn ngữ. Lưu bằng cookie `rtr_locale`, không dùng localStorage.

**Truy cập (a11y).** Đúng một `<header>`, một `<nav>`, một `<main>`, một
`<aside id="evidence-rail">` với nhãn riêng. Mỗi trang một H1 qua `PageHeader`.
`aria-current` cho mục đang chọn. Skip link, F6, quản lý tiêu điểm sau điều hướng,
combobox picker chuẩn WAI-ARIA. `role="status"` cho tải, `role="alert"` cho từ chối và
lỗi, `role="note"` cho caveat. Reduced-motion tắt chuyển động và luôn có bản chữ. Kết
quả axe **0 vi phạm** trên 5 trang × 4 viewport × 2 ngôn ngữ, keyboard E2E, 73/73
Playwright.

**Quy ước trạng thái.** `src/shared/surface.tsx` chuẩn hoá `Load<T>` = idle, loading,
ready, denied, error. **401 rớt phiên** tại chỗ, **403 hiện trạng thái từ chối mà không
rớt phiên**.

**Bảo mật proxy.** Mỗi proxy `/api/*` gắn `x-request-id`, chuyển tiếp cookie,
`redirect:"manual"`, `cache:"no-store"`, chỉ nhận segment an toàn, có **allowlist họ
đường dẫn** (ví dụ `/api/ask` chỉ cho `{ask, conversations}`), timeout (auth 5s, dữ
liệu 180s, status 3s), và trả 503 có kiểu khi upstream lỗi. Middleware chặn path
traversal, giải mã tối đa 4 lần rồi từ chối `.`/`..`.

---

## 12. Trạng thái hiện tại và khoảng cách

**Đã vững (cơ chế đầu-cuối, có gate gọi tên):** 33/34 REQ. Bao gồm fail-closed toàn
API, OIDC + RBAC/ABAC, HTTPS/quota/cost/breaker, audit append-only hash-chained, truy
hồi lai có ACL và DLP, grounding và honest-null với gap có owner, publish SOT nguyên
tử, ingestion quarantine + AV + OCR + transcript, bảy họ viewer với deep locator,
Document OS render tất định + duyệt/phát hành/thu hồi, Knowledge-Ops sống theo phạm vi,
CI + migration gate + Trivy + Playwright.

**Khoảng cách có tên:**

- **REQ-020 (partial):** truy hồi tệp đính kèm riêng của hội thoại như bằng chứng trả
  lời **chưa dựng**. Hôm nay chỉ có dạng an toàn: giới hạn theo tệp SOT đã publish,
  không rò rỉ, thiếu thì honest-null.
- **Màn Quản trị chưa có UI:** backend đã có 5 bề mặt API, mặt trước là placeholder.
- **Chất lượng thẩm mỹ:** hệ graphite tối hiện tại đúng kỷ luật nhưng ở mức chức năng.
  Nâng "trải nghiệm dẫn đầu" là một TIP tùy chọn có phạm vi hẹp, tách khỏi cơ chế.

**Hai sửa lỗi truy hồi mới nhất (02/08) đã đưa Hỏi chạy đúng end-to-end:** đổi lexical
từ `plainto_tsquery` (AND mọi từ) sang **OR** để câu hỏi tự nhiên truy được, và cho
**provider local cite mỗi câu** để fact nhiều câu qua được `verify_grounding`. Kèm tầng
**query understanding** (giải alias sản phẩm tất định, cộng LLM rewrite Anthropic→
OpenAI có fallback, env-gated) để "hera là gì" cũng mượt.

---

*Tài liệu này là snapshot X-Ray tại 02/08/2026, đọc trực tiếp mã nguồn thật. Khi UI
được nâng cấp, cập nhật mục 3 và 12, giữ nguyên phần cơ chế đã kiểm chứng.*
