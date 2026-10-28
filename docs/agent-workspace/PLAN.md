# Agent Workspace độc lập

Ngày lập: 2026-10-27. Phương pháp: Vibecode Kit v6.3, bản personal hiện hành.
Code baseline đã khảo sát: `26742a39ccdc63b904ac5b6fd4ff3afb00af6851`.

**Checkpoint 2026-10-28:** AW-01 đã lưu ở commit `347c8b2`; AW-02 đã đạt
nghiệm thu kỹ thuật **local/mock có giới hạn** trên working tree sau commit đó.
Xem [AW-02 implementation/verification](AW-02.md) và JSON evidence đi kèm.
AI thật và tìm web thật chưa nghiệm thu; không deploy, chưa mở AW-03. Các mô tả
“chưa triển khai” và quyền hạn ở phiên lập kế hoạch bên dưới là lịch sử tại ngày
lập, không phải hiện trạng mới nhất. Không sửa lại bằng chứng lịch sử.

**Cập nhật AW-03, cùng ngày:** AW-02 đã commit/push ở `e4cc75e`; AW-03 đạt
local/mock có giới hạn trên working tree sau mốc đó. Xem [AW-03](AW-03.md) và
JSON evidence cho memory, MCP stdio fixture, durable approval/effect receipts và
manual-clock schedules. AI thật/live connector chưa nghiệm thu; chưa commit/push
AW-03, không deploy và chưa tự mở AW-04.

**Cập nhật AW-04, cùng ngày:** người dùng đã giao triển khai trọn mốc AW-04.
AW-03 được checkpoint local ở `189c585`, chưa push. AW-04 đã đạt gói kỹ thuật
local/mock có giới hạn theo
[TIP AW-04](AW-04.md): setup/readiness, export/delete dữ liệu, bộ journey và
đối chứng agent, cùng kiểm thử tích hợp: Python 101, web unit 258, browser 22 và
probe độc lập 23 đều đạt trên working tree. Chưa có quyền và credential Workspace
riêng để gọi model thật. Không lấy kết quả local/mock làm nghiệm thu AI thật,
không deploy và không tự dùng credential hay corpus legacy.

**Quyết định thiết kế đề xuất: PydanticAI làm agent loop, bổ sung capability chọn lọc từ Pydantic AI Harness; thử DBOS làm chủ sở hữu duy nhất của recovery trong workflow mới.** Không đưa harness vào pipeline RAG cũ, không ghép hai executor cho cùng một run. Deep Agents/LangGraph là phương án thay thế nếu phép thử tích hợp đầu tiên bác bỏ lựa chọn này.

Đây là kế hoạch phát triển, chưa phải chứng thực harness hay bản triển khai. Người dùng đã đồng ý hướng sản phẩm độc lập và yêu cầu so sánh, lựa chọn, lập kế hoạch. Phiên này không cài dependency, chạy model trả phí, SQL/Docker, campaign, executor hoặc deploy. Quyền chạy các campaign RtR trước đây không mở rộng sang sản phẩm mới.

## 1. Sản phẩm và kết quả cần đạt

Agent Workspace dành trước hết cho cá nhân và nhóm nhỏ: giao tiếp tự nhiên, làm việc với tệp và công cụ, tạo rồi sửa đầu ra, tiếp tục việc dang dở và ghi nhớ trong phạm vi người dùng lựa chọn. Đây là lớp phần mềm điều phối công việc bằng AI, không phải hệ điều hành máy tính hoặc bản sao đầy đủ của Dots/Muse/OpenClaw.

Phân khúc đầu là người làm việc với tri thức, dự án, nghiên cứu và tài liệu. Hai công việc dẫn đường: biến một bộ nguồn thành brief/bảng dùng được; tiếp tục chỉnh sửa và cập nhật công việc đó qua nhiều phiên. Không lấy khả năng tự làm mọi công việc doanh nghiệp làm tiêu chuẩn MVP.

Giả định khởi đầu: web local-first, một deployment cho một chủ sở hữu hoặc nhóm nhỏ; hỗ trợ nhiều workspace có cách ly ngay từ đầu. Chưa làm SaaS đa khách hàng, billing, ứng dụng native, voice hoặc điều khiển toàn bộ máy tính. Model local/cloud phụ thuộc cấu hình và quyền xuất dữ liệu, không hứa local đồng nghĩa offline thông minh.

| Yêu cầu | Kết quả nhìn thấy | Nguồn và ưu tiên |
|---|---|---|
| AW-1 | Hỏi, trao đổi, suy luận, soạn thảo không cần SOT được duyệt trước | Phản hồi UX của người dùng, bắt buộc |
| AW-2 | Đưa tệp vào, giao việc, nhận đầu ra xem/sửa/tải được và tiếp tục ở lượt sau | Hướng Agent Workspace đã đồng ý, bắt buộc |
| AW-3 | Đóng tab không mất việc; Stop, reload, lỗi mạng và restart có trạng thái trung thực | Bài học vận hành cũ, bắt buộc |
| AW-4 | Kết nối công cụ/MCP theo workspace và quyền thật, không hỏi duyệt từng lần đọc hợp lệ | Hướng OS linh hoạt, bắt buộc |
| AW-5 | Ghi nhớ được xem, sửa, xoá và giới hạn phạm vi; không âm thầm biến suy luận thành sự thật | Dữ liệu và quyền hạn, bắt buộc |
| AW-6 | Một lõi không brand; RtR chỉ còn profile tuỳ chọn, không đem dữ liệu cũ vào mặc định | Người dùng đổi định hướng, bắt buộc |
| AW-7 | Giảm công thao tác lặp lại so với agent trực tiếp, không làm chất lượng ngôn ngữ suy giảm | Tiêu chuẩn AI product engineering, phải đo |

SOT trở thành công cụ tri thức có thể bật cho một workspace hoặc yêu cầu chứng thực cụ thể. Nguồn ở panel liên quan và citation gọn theo đoạn/khối nội dung; không băm câu trả lời thành hàng loạt claim-card. Nguồn mâu thuẫn được trình bày, không tự hợp thức hoá. Hội thoại, ý tưởng và bản nháp không phải hồ sơ hành chính.

## 2. So sánh harness theo code đang có

Nhận định dưới đây là so sánh thiết kế từ source và tài liệu chính thức, không phải benchmark tốc độ, chất lượng hoặc giá thành. Ưu tiên: khả năng hoàn thành việc thật, phù hợp Python async hiện tại, số phần phải tự xây, recovery/streaming, kiểm soát công cụ, rồi mới tới độ rộng hệ sinh thái.

| Phương án | Năng lực phù hợp được tài liệu mô tả | Đánh đổi khi gắn vào dự án | Kết luận |
|---|---|---|---|
| PydanticAI và capability Harness chọn lọc | Typed Python, nhiều provider, công cụ/MCP, approval; thư viện Harness có filesystem, skills, memory và context management | Cần tích hợp publisher/event journal của sản phẩm; Harness 0.x, metadata Alpha; DBOS streaming/cancel có giới hạn phải thử | **Chọn làm đường chính**, không nạp cả bộ Coder |
| Deep Agents và LangGraph | Harness Python sẵn file/context/skills, interrupt và checkpoint | Thêm stack LangChain/LangGraph và dependency; phải thay DBOS ownership, không bọc nó; backend filesystem không tự là sandbox | **Đối chứng kỹ thuật mạnh nhất**, fallback có điều kiện |
| OpenAI Agents SDK | Agent loop, tools, sessions, approvals và tích hợp sandbox; Python, nhiều provider | Session SDK không thay toàn bộ task/artifact lifecycle; vẫn cần storage và recovery integration của host | Tốt cho hướng OpenAI-first; không có lợi thế tích hợp đủ rõ để đổi lựa chọn hiện tại |
| Claude Agent SDK | Harness Claude Code, file/shell, MCP, sessions, permissions và hooks | SDK chạy binary Claude Code; phụ thuộc runtime/provider và điều khoản dịch vụ; không tự biến host process thành môi trường an toàn | Phù hợp công cụ chuyên tác vụ Claude, chưa chọn làm lõi độc lập |
| Fork OpenClaw | Một sản phẩm gateway đa kênh có runtime, sessions và tích hợp | Không phải thư viện Python thay thế trực tiếp; chuyển trọng tâm sang gateway/channels, phải mang thêm control plane và state model | Tham khảo UX/tích hợp sau, không fork làm nền lúc này |
| Tiếp tục executor tự xây hiện tại | Đã có registry, plan, audit và DBOS trong code | Registry thực thi hẹp, chịu coupling SOT/DocumentOS, chưa có general agent workspace; tiếp tục trả chi phí phát triển phần upstream đã cung cấp | Không mở rộng thành harness tổng quát |

Nguồn: [Pydantic AI Harness](https://pydantic.dev/docs/ai/harness/), [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview), [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents/sdk), [OpenAI sandbox agents](https://developers.openai.com/api/docs/guides/agents/sandboxes), [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview), [OpenClaw architecture](https://docs.openclaw.ai/concepts/architecture).

### Vì sao chọn PydanticAI

Đây là suy luận về độ phù hợp, không phải khẳng định framework tốt nhất toàn thị trường. Backend hiện là Python 3.12, FastAPI, Pydantic, async SQLAlchemy/PostgreSQL và đã khai báo DBOS 3.2.0. PydanticAI cho phép bắt đầu bằng một agent có công cụ typed, thêm capability khi có nhu cầu, không cần đổi toàn bộ backend hoặc tự viết vòng tool-calling. Deep Agents có lợi thế nếu durable graph, ngắt/tiếp tục và nhiều bước phức tạp trở thành trọng tâm vượt khả năng tích hợp này.

Không chọn vì đã đầu tư DBOS. Nếu giữ DBOS làm stream/cancel kém hoặc cần quá nhiều mã nối, bỏ lựa chọn đó. Không có nghĩa vụ cứu vãn executor TIP-054 cũ để chứng minh đầu tư trước đây đúng.

### Phiên bản và license

- PydanticAI core và Harness công bố MIT; Deep Agents và OpenAI Agents SDK cũng công bố MIT. Điều này không cấp quyền tái phân phối toàn bộ code/corpus RtR hiện có hoặc xoá nghĩa vụ dependency.
- [Manifest Harness](https://raw.githubusercontent.com/pydantic/pydantic-ai-harness/main/pyproject.toml) và [manifest core](https://raw.githubusercontent.com/pydantic/pydantic-ai/main/pydantic_ai_slim/pyproject.toml) trên main cho thấy dependency mới, bao gồm yêu cầu Pydantic mới hơn. Đây chưa phải bộ wheel được resolve với dự án. Không cài thẳng từ main hoặc tự nâng dependency toàn app.
- M1 phải chọn bản phát hành có thật, lock version/hash và lưu compatibility matrix. Tài liệu Harness và metadata có khác biệt về sàn Python; Python 3.12 hiện tại nằm trong cả hai phạm vi, nhưng chỉ resolved wheel mới xác nhận contract sử dụng. API 0.x phải được bọc trong một adapter nhỏ, không rải import khắp domain/UI.
- Xác nhận quyền sử dụng/tách thương mại mã cũ, corpus, hình ảnh, template và tên riêng trước khi phát hành độc lập. Chưa thấy license gốc ở top-level qua scan có phạm vi; đây không phải kết luận pháp lý về quyền sở hữu.
- Kiểm kê license trực tiếp và bắc cầu, đặc biệt `pymupdf` hiện có: [upstream công bố AGPL/commercial](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). Chọn tuân thủ, license phù hợp hoặc thay dependency theo tính năng; không coi tách process là tự động hết nghĩa vụ.

## 3. Kiến trúc nhỏ nhất và ranh giới tái sử dụng

```text
Web Workspace: transcript, composer, tasks, artifact preview
                       |
          Workspace API + durable event journal
                       |
         PydanticAI agent loop + selected capabilities
                       |
       Scoped tools / artifact publisher / optional knowledge
                       |
         Managed workspace storage or isolated sandbox

Recovery owner proposed: one NEW DBOS workflow per run
Legacy RAG, ActionService and executor: outside this run path
```

Một backend modular và một workspace worker đủ cho bản đầu. Không tạo microservice cho từng tool, không thêm Redis queue, Temporal, LangGraph và DBOS cùng làm chủ một run. API và worker có thể tách process vì vòng đời khác nhau; đó không phải yêu cầu tách mỗi capability thành dịch vụ.

| Thành phần hiện tại | Cách dùng lại | Ranh giới phải thay |
|---|---|---|
| Identity/session | Port xác thực, session và quyền resource | Không bắt email RtR; workspace ownership/membership rõ, không dùng department thay tenant |
| Files, object storage, ingestion | Scoped file handles, streaming I/O, checksum, staging và validation | Không cấp bucket key/host path tuỳ ý cho model; không thừa kế SOT publication gate cho bản nháp |
| Retrieval | Một knowledge tool tuỳ chọn, ACL theo người gọi | Không gọi AnswerService làm vòng lặp agent |
| Document renderers | Công cụ xác định cho template/định dạng đã hỗ trợ | Không dùng renderer PDF cũ làm engine authoring tổng quát; kiểm lỗi cắt chữ, font và template |
| Usage accounting | Chuẩn hoá token/call từ SDK theo model/run/tool/workspace | Tiền chưa biết phải ghi unknown, không tự tính bằng 0 |
| Web shell và viewers | Tái sử dụng thành phần hiển thị đã phù hợp | Contract event/task mới, không ép vào 5 trạng thái RAG hoặc 3 kết quả grounded/honest-null/failed |
| Actions/DBOS cũ | Tham khảo idempotency, outbox và cancellation fence | Không gọi ExecutionService.advance hoặc trộn lịch sử workflow cũ |

Tách adapter trung tính không được thực hiện bằng cách vô hiệu hoá guard của DocumentOS/Action Kernel cũ. Profile cũ giữ nguyên hợp đồng; publisher mới có hợp đồng riêng cho workspace draft. Chỉ chuyển dữ liệu qua adapter khi có quyền sử dụng tương ứng.

Locators từ code đã đọc, đường dẫn dưới repository:

- `v2/apps/backend/pyproject.toml`: Python và dependency hiện có; chưa khai báo harness nào trong bảng.
- `v2/apps/backend/src/rtr_copilot/api/main.py:54`: gắn router theo module.
- `v2/apps/backend/src/rtr_copilot/rag/answering.py:1080`: AnswerService ràng buộc ontology/retrieval/grounding; không phải kernel mới.
- `v2/apps/backend/src/rtr_copilot/rag/adapters.py:96`: AnswerAdapter không có hợp đồng tool events, approval hoặc resumable task.
- `v2/apps/backend/src/rtr_copilot/actions/runtime.py:1`: worker opt-in; `actions/execution.py:44`: lifecycle riêng.
- `v2/apps/backend/src/rtr_copilot/ingestion/service.py:107` và `storage/s3.py:43`: đường nhận tệp và object storage có thể bọc lại.
- `v2/apps/backend/src/rtr_copilot/documents/service.py:1389`: staged publication/outbox; guard ở `:1579` gắn policy cũ, không dùng nguyên khối.
- `v2/apps/backend/src/rtr_copilot/documents/renderers.py:168`: PDF renderer hiện tại bỏ template và có cắt chuỗi, phải loại khỏi đường authoring tổng quát cho đến khi sửa và verify.
- `v2/apps/backend/src/rtr_copilot/rag/api.py:99`: SSE request-scoped; `v2/apps/web/src/app/api/ask/[[...path]]/route.ts:46`: proxy không phải task store.
- `v2/apps/backend/src/rtr_copilot/auth/models.py`: Subject chưa có workspace identity; `rag/ontology.py:528`: active ontology hiện mang tính global.

### Một chủ sở hữu trạng thái thực thi

DBOS trong thiết kế mới chỉ là durable owner của workflow và bước đã checkpoint. Product task row là projection cho UI và lệnh điều khiển, không phải executor thứ hai. Message/event journal và artifact catalogue có trách nhiệm lưu/hiển thị riêng, không tự quyết định phát lại tool. Mỗi command có owner, run revision và idempotency key; recovery đọc cùng workflow history, không tự submit run thay thế.

Leaf job như render/ingestion vẫn có thể sở hữu vòng đời giới hạn và effect ledger của nó; đây không phải một agent-run owner thứ hai. Biên nhận tác động phải truy vấn độc lập được, có stale-worker fencing và budget reservation bền vững. Workflow checkpoint không thay quyền giao dịch của hệ thống nguồn.

Worker mới có application identity, workflow registrations và cấu hình runtime riêng, không dùng tên/schema lịch sử của executor cũ. Đăng ký agent/toolset IDs ổn định trước startup, version route hoặc drain run đang chạy trước nâng dependency. Không replay workflow cũ bằng code mới chưa kiểm tương thích.

[Tích hợp DBOS chính thức](https://pydantic.dev/docs/ai/capabilities/durable_execution/dbos/) có các điều kiện quan trọng: phải bọc run trong workflow; function tool trực tiếp không tự được checkpoint; một số stream API bị buffer; live handler có thể chạy lại; cancellation đi qua workflow. M1 phải chứng minh đường live event và tool receipts đúng trên version đã lock. Không dùng API wrapper đã deprecated hoặc hứa resume chỉ vì có session history.

Side effect ở external API không được hứa exactly-once. Tool ghi intent trước dispatch, sử dụng idempotency/reconciliation nếu endpoint hỗ trợ; kết quả chưa rõ chuyển sang trạng thái cần đối soát, không retry mù. Lỗi sau khi tạo file nhưng trước checkpoint không được tạo artifact trùng hoặc xuất bản file đã bị huỷ.

### Dữ liệu và event contract

Chỉ chuẩn hoá các thực thể cần dùng: workspace/member, conversation/message, run, tool invocation/approval/receipt, artifact/version và memory entry. Tham chiếu từ SDK qua ID, không lưu toàn bộ tệp vào prompt hoặc checkpoint. Nội dung tệp ở storage, version/checksum ở catalogue. Chưa cần knowledge graph toàn doanh nghiệp hoặc universal plan IR.

Các event tối thiểu: message delta/final, tool start/result, approval requested/resolved, artifact staged/published, usage, run state/error. Event có run ID, sequence/cursor và quyền truy cập; reconnect từ cursor không chạy lại model. Delta đang tạo được đánh dấu provisional; final snapshot và journal reconcile sau restart. Không trình diễn chain-of-thought; chỉ hiện hoạt động công cụ và kết quả cho phép.

Run có queued/running/waiting approval/completed/failed/cancelled cùng cancel requested và trạng thái effect chưa rõ. Stop báo đã nhận ngay nhưng chỉ báo cancelled khi worker đã xác nhận; đóng tab mặc định chỉ bỏ subscription. Continue sau cancelled là attempt mới có liên kết và phần công việc còn lại, không bí mật đảo trạng thái terminal. Approval pause có thể tiếp tục cùng logical run theo contract đã kiểm.

Artifact đi qua staging → validate → publish bằng revision/cancellation fence. Bản nháp được phép publish trong workspace mà không cần chứng thực SOT; bản final không tự mang ý nghĩa legal/official. Không publish tệp lỗi như thành phẩm. Draft hợp lệ còn lại phải truy cập được khi một tool sau đó lỗi.

### Quyền hạn nhẹ ở UX và nghiêm ở tool boundary

- Read, search và draft trong phạm vi đã cấp chạy không cần duyệt lặp. Gửi tin, ghi hệ thống ngoài, chi tiền, xoá hoặc xuất dữ liệu nhạy cảm dùng policy và preview đúng rủi ro.
- Approval do server tạo và lưu, gắn actor/workspace/run/tool/argument digest/expiry; thay recipient hoặc nội dung quan trọng làm mất hiệu lực. Client không tự xác nhận bằng cách gửi history hoặc cờ approved.
- Approval còn gắn source/artifact revision và policy version. Reauthorize bằng trạng thái quyền hiện tại khi đọc nguồn, gọi effect và ngay trước publish; không dùng quyền cũ đã serialize trong checkpoint. Revocation khi đang pause, approval gửi trùng và thay arguments sau duyệt đều có test.
- MCP descriptor, file, web page và skill là nội dung không tin cậy, không phải quyền thực thi. Đổi schema/quyền của tool phải kiểm lại. Secrets nằm ở broker/tool host, không chèn vào prompt, skill, event hoặc durable history.
- File path phải chặn traversal/symlink vượt root; isolation còn phải bao phủ memory/cache/event/download, không chỉ UI. Web fetch kiểm SSRF và network egress; không cho model tự truy cập cloud metadata hay loopback service bí mật.
- Không dùng `LocalWorkspace('.')`, unrestricted Coder hoặc mount home/repo/Docker socket làm mặc định trên web server. Filesystem root không phải sandbox cho shell. Bản đầu dùng công cụ file xác định; shell/browser chỉ thêm trong sandbox với quota, process cleanup và network policy đã kiểm. Không có sandbox thì capability đó chưa sẵn sàng, không fallback ra host.
- Tracing/telemetry mặc định không xuất prompt/tool content ra bên thứ ba. Cấu hình observability là một quyết định xuất dữ liệu riêng, không bật ngầm theo SDK default.

Nguồn bảo mật: [Pydantic workspace boundaries](https://pydantic.dev/docs/ai/core-concepts/workspace/), [approval trust boundary](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/), [Deep Agents backend warnings](https://docs.langchain.com/oss/python/deepagents/backends).

## 4. Bốn mốc lớn

Mỗi mốc là một TIP theo outcome, kèm một Completion/Verify tổng hợp. Không chia thành R28/R29 kéo dài chỉ để nghiên cứu từng primitive. Builder tự xử lý chi tiết L1; Contractor giải quyết tích hợp L2. Chỉ hỏi người dùng khi thay mục tiêu, xuất dữ liệu, tăng ngân sách hoặc mở quyền ngoài phạm vi đã giao.

| Mốc | Gói công việc hoàn chỉnh | Đầu ra nghiệm thu và điểm dừng |
|---|---|---|
| **AW-01 Nền tảng và lát cắt dùng được** | Resolve/pin harness; proof streaming/recovery; neutral config và sibling workspace API; một agent, file tools xác định, UI transcript/composer, lưu artifact đơn giản | Người dùng tải một bộ tệp synthetic không RtR, hỏi rồi yêu cầu tạo brief Markdown, sửa qua lượt tiếp và mở lại artifact. Không cần ontology, company email hoặc corpus RtR. Nếu integration proof thất bại, chưa mở rộng UI/capability |
| **AW-02 Workspace hoàn chỉnh cho công việc hằng ngày** | Upload nhiều tệp, preview/download/version/diff, authoring và render định dạng đã chọn, web read/search, chỉnh sửa cục bộ, UI mượt và phân quyền workspace | Tạo và sửa brief/bảng từ tệp, giữ số liệu và nội dung; bản cũ không bị ghi đè; lỗi render vẫn giữ draft. Browser E2E happy/unhappy và accessibility. Chỉ claim các định dạng đã kiểm, không hứa mọi Office |
| **AW-03 Agent bền vững và kết nối** | Industrialize restart/reconnect/cancel/budget; MCP credentials/permissions; memory xem/sửa/xoá; schedules giới hạn; sandbox cho code/browser khi đủ isolation | Resume việc hợp lệ sau restart; không gửi trùng khi timeout; từ chối approval giả; không rò workspace; xoá memory không bị phục hồi từ cache. Một MCP read và một effect mô phỏng được kiểm, trước kết nối tài khoản thật |
| **AW-04 Chất lượng và independent pilot** | Holdout user journeys, đối chứng agent trực tiếp, đo tổng công/cost/latency, security/recovery/load theo tải công bố, packaging và license, dọn legacy khỏi default deployment | Local pilot có hướng dẫn ngắn, export/delete được dữ liệu; không lỗi P0/P1 còn mở trong phạm vi; công bố mức đã chứng minh và giới hạn. Không tự đổi AI simulated review thành human acceptance hoặc release GO |

AW-01 → AW-02 → AW-03 → AW-04. Recovery nền tảng phải qua proof từ AW-01; không đợi AW-03 mới phát hiện harness không stream được. Memory/MCP cơ bản có thể được chứng minh bằng fixture sớm, nhưng chưa mở connector hoặc scheduler thật để làm demo.

Không đưa vào critical path: tái chứng thực campaign RtR, chuẩn hoá ontology toàn công ty, mọi kênh chat, agent swarm, skill marketplace, enterprise SaaS/SSO/TLS production, chuyển toàn repo/package name một lần hoặc viết lại mọi renderer. Giữ legacy ở profile opt-in để tránh hồi quy diện rộng; không rewrite dữ liệu cũ tại chỗ.

## 5. TIP AW-01 sẵn sàng giao Builder sau quyết định triển khai

**Outcome:** chứng minh một người dùng làm được việc với tệp trong Workspace không brand và có đường durable khả thi, trước khi mở rộng tính năng.

**Phạm vi:** trong checkout hiện tại, tạo module/package trung tính và feature route riêng; dependency runtime mới tách lock/environment nếu xung đột, không tự nâng toàn bộ app. Tận dụng PostgreSQL/storage hiện có ở giai đoạn tích hợp, không dựng thêm cả hệ thống chỉ cho một spike. Không xoá legacy, không bật executor cũ.

### Proof trước khi mở rộng

Timebox đề xuất: tối đa hai ngày công kỹ thuật cho proof harness, không phải hai ngày chạy model. Đây là ngưỡng lập kế hoạch, chưa phải ngân sách API được người dùng cấp. Có một đợt sửa hẹp cho lỗi wiring trong cùng timebox; không lặp so sánh campaign vô hạn. Sau proof cập nhật ước lượng AW-01 và lịch các mốc còn lại theo công thực tế.

Chọn PydanticAI trước; Deep Agents/LangGraph chỉ triển khai cùng protocol fixture tối thiểu nếu đường chính vướng blocker, hoặc cần giải quyết đánh đổi chưa rõ. Tối đa hai stack trong proof; không xây hai Workspace đầy đủ. Không dùng kết quả mock để chọn model hoặc tuyên bố token rẻ hơn.

| Case proof | Điều phải quan sát |
|---|---|
| C1 Stream thật về event handler | Mock model phát từng delta theo clock điều khiển; UI/client nhận trước final; reload không phát lại model |
| C2 Crash trước/sau tool receipt | Checkpoint và idempotency phân biệt rõ; không double publish hoặc gửi lại effect chưa đối soát; recovery không reset deadline/budget |
| C3 Approval pause và forged client | Resume hợp lệ được; đổi arguments, actor, policy/quyền nguồn hoặc history giả bị chặn ở server/tool; approval trùng không lặp effect |
| C4 Stop trong model/tool | Giao diện báo requested ngay; worker xác nhận terminal có giới hạn; không publish sau cancellation fence |
| C5 Scope và hostile input | Traversal, symlink, cross-workspace IDs, prompt injection, secret exfiltration không vượt tool authority |
| C6 Budget và outage | Dừng trước dispatch vượt giới hạn; 429/timeout không replay mù; draft tốt còn truy cập được |
| C7 Conversation và artifact | Follow-up sửa đúng artifact version, không lẫn draft/completed; Unicode và nội dung dài không bị cắt |
| C8 Clean start và no brand | Chạy không corpus/ontology RtR, không bắt domain công ty; dependency resolve có lock và license inventory |

C2/C4 cần worker và database thực ở integration lane để kết luận recovery/cancel; mock chỉ kiểm event/schema/control logic. Chạy SQL/Docker để chứng minh những ca đó là công việc triển khai tiếp theo khi được giao, không nằm trong phiên lập kế hoạch này. Provider trả phí là một lane riêng, dùng dataset synthetic/public được phép và trần chi phí đã chốt; chưa gọi trong proof offline.

Proof dùng mock không đủ đóng AW-01 ở mức dùng được. Lát cắt user-facing cần model thật trong cấu hình được cho phép, với evidence prompt/input/output và chất lượng đầu ra. Nếu chưa có quyền/ngân sách hoặc model khả dụng, chỉ chốt phần structural/integration đã kiểm và ghi AW-01 PARTIAL, không quảng cáo đã có agent hoạt động.

Nếu không đạt live streaming, cancel fence hoặc restart an toàn bằng upstream primitives và adapter nhỏ, chuyển proof sang Deep Agents/LangGraph, bỏ DBOS cho các run mới. Nếu cả hai đều cần framework tự xây lớn, thu hẹp bản đầu thành agent có file/tools và không hứa background/restart cho đến khi có giải pháp; phải nêu thay đổi contract trước triển khai phụ thuộc.

Nếu PydanticAI slim một mình cùng các port cần thiết đạt cùng outcome ít phức tạp hơn, bỏ dependency Harness chưa tạo giá trị. Không giữ thư viện vì đã ghi tên trong kế hoạch. Deep Agents có backend state/composite phù hợp, không bị loại vì ví dụ host filesystem không an toàn; phải so đúng backend và cùng quality floor.

### AC kết thúc mốc

- Một flow browser: tạo workspace → upload → chat → tạo file → sửa file bằng follow-up → tải và mở lại sau reload. Text đã gửi biến khỏi composer ngay; submit trùng không tạo run thứ hai.
- Transcript render Markdown chuyên nghiệp, không chia theo dấu chấm thành từng claim; nguồn gọn và mở được ở panel; composer neo đáy, scroll/focus/keyboard/mobile không che nội dung.
- Có synthetic failure flows ở proof trên và integration evidence phân biệt rõ; capability chưa kiểm phải ở trạng thái unavailable, không giả pass.
- Mỗi run có usage, limit, trace nội bộ có redaction; không có credential trong prompt/event/log/checkpoint. Biết model đang unavailable ngay từ đầu, không treo tìm nguồn một phút rồi mới báo cấu hình.
- Existing selected auth/file/policy regressions vẫn đạt trong môi trường đủ dependency; package cũ không bị mass-upgrade. Mọi skip/missing dependency được ghi, không chuyển thành product pass.

### Ngân sách và latency mục tiêu

Một agent chính, không planner/reviewer model riêng mặc định. Cho agent chọn công cụ theo intent từ cùng lượt; đọc/search song song chỉ khi độc lập và không phá budget. Large tool output có giới hạn/spill theo scope. Retry chỉ cho lỗi tạm thời có cơ sở, tối đa một lần ở mặc định đề xuất, không tự retry effect chưa rõ; tổng deadline/call/token/output-byte limit tính cả repair và compaction. Concurrency ban đầu thấp, tăng sau đo.

Mục tiêu UI đề xuất: ACK/placeholder ≤300 ms p95 local; trạng thái tool có ý nghĩa trong ≤1 giây sau event host nhận; Stop chuyển sang requested ngay. Đây không phải cam kết model tạo token trong 300 ms. Đo riêng first useful text, first tool result và time to usable artifact. Adapter overhead theo cùng model/tool: mục tiêu không thêm model call trên happy path, host overhead p95 ≤200 ms trong probe có ít nhất 100 lượt local không gọi model; công bố phần cứng và số mẫu. Những con số này là mục tiêu cần kiểm, chưa phải số đo hiện tại.

Trần USD cho real-model evaluation chưa có trong request này. Phải có giới hạn tổng trước khi chạy; không suy từ API credit còn lại. Ước lượng token × giá provider theo cấu hình thật, cập nhật sau smoke nhỏ và dừng ở trần; không đặt fallback sang provider hoặc nguồn dữ liệu khác ngoài quyền đã cấp.

## 6. Đối chứng và nghiệm thu giá trị sản phẩm

Tách hai câu hỏi: harness nào dễ tích hợp và chạy đúng contract; Workspace có làm công việc người dùng tốt hơn agent trực tiếp hay không. Không lấy test count của câu hỏi thứ nhất làm đáp án cho câu hỏi thứ hai.

| Đối chứng | Điều kiện và kết luận hợp lệ |
|---|---|
| Một LLM trực tiếp | Chat/soạn thảo cùng model và context, không giả vờ nó có tool. Kiểm Workspace không làm giảm chất lượng vì protocol |
| Agent trực tiếp có công cụ | Cùng model/provider/settings, tệp, công cụ, network/quyền và budget với Workspace khi khả thi; so tổng công tạo/sửa/tìm lại đầu ra |
| Workspace | Thêm UI, artifact/version, scoped memory, reconnect và quyền hạn; lợi thế phải xuất hiện ở một công việc cụ thể, không cần thắng mọi chiều |

Tập đánh giá dự kiến gồm 12 journey, không dùng để hardcode câu trả lời: chat/follow-up; tóm tắt nhiều tệp; tạo brief dài; giữ số liệu trong bảng; sửa một phần artifact; research có nguồn mâu thuẫn; thiếu tệp; tool timeout/429; restart/reconnect; cancel sau effect; approval giả/revoked access; memory sai scope/forget. Dữ liệu không RtR, có ít nhất hai domain khác nhau. Giữ một nửa biến thể/input chưa dùng để phát triển, đóng băng trước evaluation; sửa trên failure thì lần đo sau dùng holdout mới và giữ lịch sử lỗi.

Lưu model/version, inputs/digest, provider endpoint class, tool scope, network mode, hardware, cold/warm, human instructions, calls/tokens/known money, time to first useful output, time to usable artifact và phút can thiệp chủ động. Nêu khác biệt không thể cân bằng. Quyền lợi dự kiến: ít phải tải lại tệp/giải thích lại/sửa thủ công và tìm lại việc hơn agent trực tiếp, không giả định lời văn hay hơn cùng model.

Quality floors: không sai số/chủ thể quan trọng đã có trong nguồn; không mất nội dung được yêu cầu trong format hỗ trợ; không rò dữ liệu; không effect trái quyền; không báo thành công giả; không làm mất draft hợp lệ. Useful partial output được phép nếu ghi đúng phần thiếu, không bịa hoàn tất.

Mức giảm ít nhất 25% thao tác chủ động trên một nhóm công việc lặp lại được đề xuất làm ngưỡng lợi thế có ý nghĩa, không phải kết quả đã đo; chốt nhóm và cách đếm trước evaluation. Không đạt thì giảm protocol/tính năng, đổi harness nếu có nguyên nhân, hoặc thu hẹp thành bộ tools cho agent. Không mở thêm agent reviewer để cứu điểm mà chưa đo chi phí.

Structural assertions, semantic review của AI và human acceptance ghi tách. AI có thể mô phỏng người dùng và phát hiện bug, không tự đóng vai người dùng thật đã hài lòng. Pilot chỉ gọi là được human acceptance trong phần một người thực đã dùng và xác nhận.

## 7. Tiến độ và bằng chứng của phiên lập kế hoạch

- **Hoàn tất:** khảo sát source ở baseline nêu đầu tài liệu; một Builder scan read-only kiểm integration seams; đối chiếu tài liệu chính thức và metadata upstream; lựa chọn kiến trúc, bốn mốc và TIP AW-01.
- **Review thiết kế độc lập:** một agent khác kiểm source và lựa chọn harness, không phải tác giả kế hoạch. Kết luận ủng hộ lựa chọn có điều kiện ở M1, chưa phải production selection; bổ sung các ranh giới effect ledger, live authorization, event recovery và build/runtime identity. Review này không phải kiểm thử implementation hoặc human acceptance.
- **Chưa triển khai:** harness, dependency resolution, neutral runtime, migrations, Workspace UI mới và các AC runtime ở trên. Tất cả scenario product ở kế hoạch đều **UNTESTED**; không có số liệu API/cost/latency mới.
- **Kiểm tra phiên này:** chỉ đọc code/tài liệu công khai và lập kế hoạch. Tracked tree ban đầu sạch. Không cài/build/Docker nên không tạo image, distDir hoặc bản sao dự án cần dọn. Không đọc secret hoặc gửi corpus nội bộ ra dịch vụ model.
- **Phần legacy:** NOT_READY và executor OFF theo báo cáo R27 lịch sử; đây không phải kết quả kiểm runtime hôm nay. Hướng mới không tự sửa hoặc bật các gate đó.
- **Bước triển khai hợp lý:** AW-01 theo phạm vi trên. Bốn mốc thay thế việc nối chuỗi micro-task của executor cũ trong roadmap phát triển mới; không sửa lại lịch sử evidence để giả đã hoàn tất.

Kết luận: READY cho thảo luận/giao kế hoạch AW-01, **NOT READY cho tuyên bố sản phẩm độc lập đã hoạt động hoặc phát hành**. Giá trị so với agent trực tiếp và chi phí thực thi vẫn chưa đo.

### Nguồn chính đã đối chiếu

Tài liệu upstream có thể đổi sau ngày lập. Pin bản phát hành và contract sử dụng ở M1; không coi README main là chứng thực wheel.

- [Pydantic AI Harness](https://pydantic.dev/docs/ai/harness/), [workspace boundaries](https://pydantic.dev/docs/ai/core-concepts/workspace/), [DBOS integration](https://pydantic.dev/docs/ai/capabilities/durable_execution/dbos/), [deferred tool trust model](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/).
- [Harness source metadata](https://raw.githubusercontent.com/pydantic/pydantic-ai-harness/main/pyproject.toml), [Harness MIT](https://raw.githubusercontent.com/pydantic/pydantic-ai-harness/main/LICENSE), [core MIT](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE).
- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview), [backends](https://docs.langchain.com/oss/python/deepagents/backends), [HITL](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop), [source metadata](https://raw.githubusercontent.com/langchain-ai/deepagents/main/libs/deepagents/pyproject.toml), [MIT](https://github.com/langchain-ai/deepagents/blob/main/LICENSE).
- [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents/sdk), [runtime options](https://developers.openai.com/api/docs/guides/agents), [sandbox agents](https://developers.openai.com/api/docs/guides/agents/sandboxes), [MIT](https://raw.githubusercontent.com/openai/openai-agents-python/main/LICENSE).
- [Claude Agent SDK overview and authentication constraints](https://code.claude.com/docs/en/agent-sdk/overview), [SDK source runtime](https://raw.githubusercontent.com/anthropics/claude-agent-sdk-python/main/README.md), [SDK wrapper MIT](https://raw.githubusercontent.com/anthropics/claude-agent-sdk-python/main/LICENSE). Wrapper license không thay điều khoản của binary/provider.
- [OpenClaw gateway architecture](https://docs.openclaw.ai/concepts/architecture), [package metadata](https://raw.githubusercontent.com/openclaw/openclaw/main/package.json).
- [PyMuPDF licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright).
