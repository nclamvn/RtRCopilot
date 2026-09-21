#!/usr/bin/env python3
"""TIP-050 · bàn thử tự động cho trục use_class và bộ số master TIP-049.

Chạy thật vào stack đang chạy: đăng nhập bằng luồng dev-OIDC có sẵn, hỏi từng
câu trong bộ oracle đã cam kết trước ở TIP-050_VERIFY_RUNBOOK.md, so kết quả
với kỳ vọng và in bảng PASS/FAIL. Không mock gì, không tự nới kỳ vọng.

Chỉ dùng thư viện chuẩn, không cần httpx, không cần venv của backend, nên chạy
được bằng bất kỳ python3 nào trên máy Homeowner:

    python3 eval/tip050/capture_use_class.py --base http://127.0.0.1:18000

Thoát 0 khi mọi case P0 đạt, thoát 1 khi có P0 hỏng, thoát 2 khi không đăng
nhập được. Bản ghi đầy đủ ghi ra --out để đính kèm Verify report.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

#: Mỗi case: mã, mức nghiêm trọng, câu hỏi, ngữ cảnh, và kỳ vọng.
#: ``expect`` là "grounded" hoặc "honest_null".
#: ``must`` là các chuỗi PHẢI có trong câu trả lời (không phân biệt hoa thường).
#: ``must_not`` là các chuỗi KHÔNG ĐƯỢC có.
CASES: list[dict[str, Any]] = [
    {
        "id": "BU-001", "severity": "P0", "use_class": "proposal",
        "q": "RtR có thu hồi quyền truy cập khi nhân viên nghỉ việc không?",
        "expect": ["grounded"], "must": [], "must_not": [],
        "must_cite": ["L3F.INF."],
        "note": "Nguồn duy nhất là lời chứng thực hành L3F.INF.021/062.",
    },
    {
        "id": "BU-002", "severity": "P0", "use_class": "attestation",
        "q": "RtR có thu hồi quyền truy cập khi nhân viên nghỉ việc không?",
        "expect": ["honest_null"], "must": ["chứng thực", "L3F.INF."],
        "must_not": ["Google Workspace"], "must_cite": [],
        "note": "Trục use_class phải loại lời chứng và nói rõ vì sao.",
    },
    {
        "id": "BU-003a", "severity": "P0", "use_class": "proposal",
        "q": "RtR có chứng nhận SOC 2 không?",
        "expect": ["honest_null", "grounded"], "must": [],
        "must_not": ["đã đạt SOC 2", "có SOC 2", "SOC 2 compliant", "L3F.ENT.001"],
        "must_cite": [],
        "note": "Registry không có fact nào nhắc SOC 2. Trả lời được hay không "
                "đều chấp nhận, nhưng tuyệt đối không ngụ ý có, và không được "
                "lấy bản ghi tên pháp nhân ra làm câu trả lời.",
    },
    {
        "id": "BU-003b", "severity": "P0", "use_class": "attestation",
        "q": "RtR có chứng nhận SOC 2 không?",
        "expect": ["honest_null", "grounded"], "must": [],
        "must_not": ["đã đạt SOC 2", "có SOC 2", "SOC 2 compliant", "L3F.ENT.001"],
        "must_cite": [],
        "note": "Như trên, ở ngữ cảnh chặt nhất.",
    },
    {
        "id": "BU-004a", "severity": "P0", "use_class": "proposal",
        "q": "Dữ liệu của RtR được lưu ở đâu?",
        "expect": ["grounded"], "must": ["us-east-1"], "must_not": ["không dùng cloud"],
        "must_cite": ["L3F.INF.002"],
        "note": "Phân xử 18/09: nêu region cụ thể. Dò 21/09 cho thấy L3F.INF.002 "
                "vắng mặt ngay ở /search với cách hỏi này, nên đây còn là phép "
                "thử độ thu hồi.",
    },
    {
        "id": "BU-004b", "severity": "P1", "use_class": "attestation",
        "q": "Dữ liệu của RtR được lưu ở đâu?",
        "expect": ["honest_null"], "must": ["chứng thực"], "must_not": [],
        "must_cite": [],
        "note": "Cư trú dữ liệu thuộc sàn cứng nhóm 3 nhưng nguồn duy nhất đang "
                "là lời chứng. Phát hiện F1 của TIP-050.",
    },
    {
        "id": "BU-005", "severity": "P0", "use_class": "proposal",
        "q": "HERA mang được tải trọng tối đa bao nhiêu?",
        "expect": ["grounded"], "must": ["14"], "must_not": ["15 kg"],
        "must_cite": ["SPEC.HERA.PAYLOAD.MAX", "HC-001"],
        "note": "Canh luật mới không làm trôi số sản phẩm đã siết ở TIP-046.",
    },
    {
        "id": "BU-006", "severity": "P1", "use_class": "proposal",
        "q": "Bao giờ RtR có giải pháp quản lý thiết bị tập trung MDM?",
        "expect": ["grounded"], "must": [], "must_not": ["đã triển khai", "đã có MDM"],
        "must_cite": ["L3F.INF.090"],
        "note": "L3F.INF.090 là cam kết lộ trình, phải đọc ra là tương lai.",
    },
    {
        "id": "UC-005", "severity": "P0", "use_class": None,
        "q": "HERA mang được tải trọng tối đa bao nhiêu?",
        "expect": ["grounded"], "must": ["14"], "must_not": [],
        "must_cite": ["SPEC.HERA.PAYLOAD.MAX", "HC-001"],
        "note": "Không nêu ngữ cảnh: mặc định proposal, kết quả phải y như BU-005.",
    },
    {
        "id": "UC-007", "severity": "P0", "use_class": "attestation",
        "q": "HERA mang được tải trọng tối đa bao nhiêu?",
        "expect": ["grounded"], "must": ["14"], "must_not": [],
        "must_cite": ["SPEC.HERA.PAYLOAD.MAX", "HC-001"],
        "note": "Nguồn ở tầng đủ tư cách chứng thực, nên cổng mới KHÔNG được chặn.",
    },
    {
        "id": "MS-009", "severity": "P0", "use_class": "proposal",
        "q": "HeraSight Standard có độ nhạy nhiệt NETD bao nhiêu?",
        "expect": ["grounded"], "must": ["40"], "must_not": [],
        "must_cite": ["SPEC.HERASIGHT.STD.NETD"],
        "note": "TIP-049 tách NETD bốn biến thể. Dò 21/09: bản ghi này hạng 1 ở /search.",
    },
    {
        "id": "MS-010", "severity": "P0", "use_class": "proposal",
        "q": "HeraSight61 NDAA có độ nhạy nhiệt NETD bao nhiêu?",
        "expect": ["grounded"], "must": ["20"], "must_not": [],
        "must_cite": ["SPEC.HERASIGHT61.NDAA.NETD"],
        "note": "Lượt 21/09 PASS giả vì trích HC-001 mà vẫn có chữ 20.",
    },
    {
        "id": "MS-011", "severity": "P0", "use_class": "proposal",
        "q": "VEGA có RTK tích hợp sẵn hay chỉ tương thích?",
        "expect": ["grounded"], "must": ["tương thích"], "must_not": [],
        "must_cite": ["SPEC.VEGA.RTK"],
        "note": "Phân xử 21/09: hỗ trợ cả hai. Dò 21/09: bản ghi này hạng 1 với lex 1,7.",
    },
    {
        "id": "MS-012", "severity": "P1", "use_class": "proposal",
        "q": "HERA có hỗ trợ RTK-GNSS không?",
        "expect": ["grounded"], "must": ["RTK"], "must_not": [],
        "must_cite": ["SPEC.HERA.RTK", "SPEC.HERA.GNSS"],
        "note": "Còn mở 049.1: HERA có cấu hình tích hợp sẵn như VEGA không.",
    },
    {
        "id": "MS-013", "severity": "P0", "use_class": "proposal",
        "q": "Quy ước đánh số phiên bản sản phẩm phần cứng của RtR là gì?",
        "expect": ["grounded"], "must": ["1.0"], "must_not": [],
        "must_cite": ["L3F.STD.001"],
        "note": "Lượt 21/09 bị từ chối vì bộ lập kế hoạch ngữ nghĩa chưa sẵn sàng, "
                "không phải vì thiếu dữ liệu: /search xếp L3F.STD.001 hạng 1 với lex 2,4.",
    },
    {
        "id": "MS-014", "severity": "P1", "use_class": "attestation",
        "q": "RtR đã có bản scan chứng nhận ISO 9001 trong hệ thống chưa?",
        "expect": ["grounded"], "must": ["ISO 9001"], "must_not": [],
        "must_cite": ["L3F.CERT.002", "L3F.CERT.001"],
        "note": "L3F.CERT.002 tầng derived_from_verified, đủ tư cách chứng thực.",
    },
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Luồng dev-OIDC cần đọc Location từng chặng, không được tự đi theo."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Client:
    """Client tối giản trên thư viện chuẩn: giữ cookie, không tự theo redirect."""

    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            NoRedirect(),
        )

    def _send(self, request: urllib.request.Request) -> tuple[int, Any, bytes]:
        try:
            with self.opener.open(request, timeout=180) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            # 3xx tới đây vì NoRedirect; 4xx/5xx cũng vậy. Cookie đã được xử lý.
            return error.code, error.headers, error.read()

    def get(self, url: str) -> tuple[int, Any, bytes]:
        return self._send(urllib.request.Request(url, headers={"Accept": "application/json"}))

    def post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, Any, bytes]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        return self._send(request)


def login(client: Client, base: str, email: str, sub: str) -> dict[str, Any]:
    _, headers, _ = client.get(f"{base}/auth/login")
    first = urlparse(headers["Location"]).query
    _, headers, _ = client.get(f"{base}/auth/dev/authorize?{first}&email={email}&sub={sub}")
    second = urlparse(headers["Location"]).query
    client.get(f"{base}/auth/callback?{second}")
    status, _, body = client.get(f"{base}/auth/me")
    if status != 200:
        raise RuntimeError(f"auth/me trả {status}: {body[:200]!r}")
    return dict(json.loads(body))


def run_case(client: Client, base: str, case: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"question": case["q"]}
    if case["use_class"] is not None:
        body["use_class"] = case["use_class"]
    status, _, raw = client.post_json(f"{base}/api/v1/ask", body)
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {"raw": raw.decode("utf-8", "replace")[:500]}
    answer = str(payload.get("answer", ""))
    state = str(payload.get("state", ""))
    lowered = answer.lower()
    cited = [str(item.get("record_key", "")) for item in payload.get("citations", [])]
    failures: list[str] = []
    if status != 200:
        failures.append(f"http {status}")
    if state not in case["expect"]:
        failures.append(f"state {state!r} ngoài kỳ vọng {case['expect']!r}")
    for needle in case["must"]:
        if needle.lower() not in lowered:
            failures.append(f"thiếu {needle!r}")
    for needle in case["must_not"]:
        if needle.lower() in lowered or any(needle in key for key in cited):
            failures.append(f"có chuỗi cấm {needle!r}")
    # Bài học lượt 21/09: chỉ kiểm chuỗi con là ra PASS giả. Một câu trả lời
    # đúng chữ nhưng trích sai bản ghi vẫn là câu trả lời sai.
    wanted = case.get("must_cite") or []
    if wanted and state == "grounded":
        if not any(any(key.startswith(w) or w in key for key in cited) for w in wanted):
            failures.append(f"trích {cited or '-'} thay vì {wanted}")
    if state == "honest_null" and case["expect"] == ["honest_null"] and cited:
        failures.append(f"honest-null mà vẫn có citation {cited}")
    return {
        "id": case["id"],
        "severity": case["severity"],
        "use_class": case["use_class"],
        "question": case["q"],
        "note": case["note"],
        "http_status": status,
        "state": state,
        "answer": answer,
        "reason_code": payload.get("reason_code"),
        "citations": [
            {
                "record_key": item.get("record_key"),
                "provenance_level": item.get("provenance_level"),
                "source_label": item.get("source_label"),
            }
            for item in payload.get("citations", [])
        ],
        "failures": failures,
        "verdict": "PASS" if not failures else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18000")
    parser.add_argument("--email", default="staff@rtrobotics.com")
    parser.add_argument("--sub", default="dev-staff")
    parser.add_argument("--out", default="eval/tip050/use_class_capture.json")
    parser.add_argument("--only", default="", help="lọc theo mã case, phân tách bằng dấu phẩy")
    args = parser.parse_args()

    wanted = {item.strip() for item in args.only.split(",") if item.strip()}
    selected = [case for case in CASES if not wanted or case["id"] in wanted]
    client = Client()
    try:
        subject = login(client, args.base, args.email, args.sub)
    except Exception as error:  # noqa: BLE001
        print(f"Không đăng nhập được vào {args.base}: {error}")
        return 2
    results = [run_case(client, args.base, case) for case in selected]

    width = max(len(item["id"]) for item in results)
    print()
    print(f"{'CASE'.ljust(width)}  SEV   NGỮ CẢNH     KẾT QUẢ  CHI TIẾT")
    for item in results:
        context = str(item["use_class"] or "mặc định").ljust(11)
        detail = "; ".join(item["failures"]) if item["failures"] else item["state"]
        print(
            f"{item['id'].ljust(width)}  {item['severity']}    {context}  "
            f"{item['verdict'].ljust(7)}  {detail}",
        )
    failed_p0 = [i for i in results if i["verdict"] == "FAIL" and i["severity"] == "P0"]
    failed_p1 = [i for i in results if i["verdict"] == "FAIL" and i["severity"] == "P1"]
    print()
    print(
        f"Tổng {len(results)} case: "
        f"{len(results) - len(failed_p0) - len(failed_p1)} PASS, "
        f"{len(failed_p0)} P0 FAIL, {len(failed_p1)} P1 FAIL",
    )
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump({"subject": subject, "results": results}, handle, ensure_ascii=False, indent=2)
    print(f"Bản ghi đầy đủ: {args.out}")
    return 1 if failed_p0 else 0


if __name__ == "__main__":
    sys.exit(main())
