#!/usr/bin/env python3
"""TIP-050 · bàn thử tự động cho trục use_class và bộ số master TIP-049.

Chạy thật vào stack đang chạy: đăng nhập bằng luồng dev-OIDC có sẵn, hỏi từng
câu trong bộ oracle đã cam kết trước ở TIP-050_VERIFY_RUNBOOK.md, so kết quả
với kỳ vọng và in bảng PASS/FAIL. Không mock gì, không tự nới kỳ vọng.

    python3 eval/tip050/capture_use_class.py --base http://127.0.0.1:18000

Thoát 0 khi mọi case P0 đạt, thoát 1 khi có P0 hỏng, thoát 2 khi không đăng
nhập được. Bản ghi đầy đủ ghi ra --out để đính kèm Verify report.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.parse import urlparse

import httpx

#: Mỗi case: mã, mức nghiêm trọng, câu hỏi, ngữ cảnh, và kỳ vọng.
#: ``expect`` là "grounded" hoặc "honest_null".
#: ``must`` là các chuỗi PHẢI có trong câu trả lời (không phân biệt hoa thường).
#: ``must_not`` là các chuỗi KHÔNG ĐƯỢC có.
CASES: list[dict[str, Any]] = [
    {
        "id": "BU-001", "severity": "P0", "use_class": "proposal",
        "q": "RtR có thu hồi quyền truy cập khi nhân viên nghỉ việc không?",
        "expect": "grounded", "must": [], "must_not": [],
        "note": "Nguồn duy nhất là lời chứng thực hành L3F.INF.021/062.",
    },
    {
        "id": "BU-002", "severity": "P0", "use_class": "attestation",
        "q": "RtR có thu hồi quyền truy cập khi nhân viên nghỉ việc không?",
        "expect": "honest_null", "must": ["chứng thực", "L3F.INF."],
        "must_not": ["Google Workspace"],
        "note": "Trục use_class phải loại lời chứng và nói rõ vì sao.",
    },
    {
        "id": "BU-003a", "severity": "P0", "use_class": "proposal",
        "q": "RtR có chứng nhận SOC 2 không?",
        "expect": "honest_null", "must": [],
        "must_not": ["đã đạt SOC 2", "có SOC 2", "SOC 2 compliant"],
        "note": "Registry không có fact nào nhắc SOC 2. Tuyệt đối không được ngụ ý có.",
    },
    {
        "id": "BU-003b", "severity": "P0", "use_class": "attestation",
        "q": "RtR có chứng nhận SOC 2 không?",
        "expect": "honest_null", "must": [],
        "must_not": ["đã đạt SOC 2", "có SOC 2", "SOC 2 compliant"],
        "note": "Như trên, ở ngữ cảnh chặt nhất.",
    },
    {
        "id": "BU-004a", "severity": "P0", "use_class": "proposal",
        "q": "Dữ liệu của RtR được lưu ở đâu?",
        "expect": "grounded", "must": ["us-east-1"], "must_not": ["không dùng cloud"],
        "note": "Phân xử 18/09: nêu region cụ thể, không còn nói on-premises.",
    },
    {
        "id": "BU-004b", "severity": "P1", "use_class": "attestation",
        "q": "Dữ liệu của RtR được lưu ở đâu?",
        "expect": "honest_null", "must": ["chứng thực"], "must_not": [],
        "note": "Cư trú dữ liệu thuộc sàn cứng nhóm 3 nhưng nguồn duy nhất đang là "
                "lời chứng. Đây là phát hiện F1 của TIP-050, chờ Homeowner phân xử.",
    },
    {
        "id": "BU-005", "severity": "P0", "use_class": "proposal",
        "q": "HERA mang được tải trọng tối đa bao nhiêu?",
        "expect": "grounded", "must": ["14"], "must_not": ["15 kg"],
        "note": "Canh luật mới không làm trôi số sản phẩm đã siết ở TIP-046.",
    },
    {
        "id": "BU-006", "severity": "P1", "use_class": "proposal",
        "q": "Bao giờ RtR có giải pháp quản lý thiết bị tập trung MDM?",
        "expect": "grounded", "must": [], "must_not": ["đã triển khai", "đã có MDM"],
        "note": "L3F.INF.090 là cam kết lộ trình, phải đọc ra là tương lai.",
    },
    {
        "id": "UC-005", "severity": "P0", "use_class": None,
        "q": "HERA mang được tải trọng tối đa bao nhiêu?",
        "expect": "grounded", "must": ["14"], "must_not": [],
        "note": "Không nêu ngữ cảnh: mặc định proposal, kết quả phải y như BU-005.",
    },
    {
        "id": "UC-007", "severity": "P0", "use_class": "attestation",
        "q": "HERA mang được tải trọng tối đa bao nhiêu?",
        "expect": "grounded", "must": ["14"], "must_not": [],
        "note": "Nguồn là SPEC.HERA.PAYLOAD.MAX tầng approved_internal, đủ tư cách "
                "chứng thực, nên cổng mới KHÔNG được chặn.",
    },
    {
        "id": "MS-009", "severity": "P0", "use_class": "proposal",
        "q": "HeraSight Standard có độ nhạy nhiệt NETD bao nhiêu?",
        "expect": "grounded", "must": ["40"], "must_not": [],
        "note": "TIP-049 tách NETD bốn biến thể.",
    },
    {
        "id": "MS-010", "severity": "P0", "use_class": "proposal",
        "q": "HeraSight61 NDAA có độ nhạy nhiệt NETD bao nhiêu?",
        "expect": "grounded", "must": ["20"], "must_not": [],
        "note": "Biến thể NDAA nhạy hơn bản Standard.",
    },
    {
        "id": "MS-011", "severity": "P0", "use_class": "proposal",
        "q": "VEGA có RTK tích hợp sẵn hay chỉ tương thích?",
        "expect": "grounded", "must": ["tương thích"], "must_not": [],
        "note": "Phân xử 21/09: hỗ trợ cả hai, tùy yêu cầu khách hàng.",
    },
    {
        "id": "MS-012", "severity": "P1", "use_class": "proposal",
        "q": "HERA có hỗ trợ RTK-GNSS không?",
        "expect": "grounded", "must": ["RTK"], "must_not": [],
        "note": "Còn mở 049.1: HERA có cấu hình tích hợp sẵn như VEGA không.",
    },
    {
        "id": "MS-013", "severity": "P0", "use_class": "proposal",
        "q": "Quy ước đánh số phiên bản sản phẩm phần cứng của RtR là gì?",
        "expect": "grounded", "must": ["1.0"], "must_not": [],
        "note": "L3F.STD.001, phân xử 21/09: phần cứng chỉ dùng phiên bản lớn.",
    },
    {
        "id": "MS-014", "severity": "P1", "use_class": "attestation",
        "q": "RtR đã có bản scan chứng nhận ISO 9001 trong hệ thống chưa?",
        "expect": "grounded", "must": ["ISO 9001"], "must_not": [],
        "note": "L3F.CERT.002 tầng derived_from_verified, đủ tư cách chứng thực. "
                "Câu trả lời phải nói CHƯA có scan.",
    },
]


def login(client: httpx.Client, base: str, email: str, sub: str) -> dict[str, Any]:
    response = client.get(f"{base}/auth/login", follow_redirects=False)
    first = urlparse(response.headers["location"]).query
    response = client.get(
        f"{base}/auth/dev/authorize?{first}&email={email}&sub={sub}",
        follow_redirects=False,
    )
    second = urlparse(response.headers["location"]).query
    client.get(f"{base}/auth/callback?{second}", follow_redirects=False)
    return dict(client.get(f"{base}/auth/me").json())


def run_case(client: httpx.Client, base: str, case: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"question": case["q"]}
    if case["use_class"] is not None:
        body["use_class"] = case["use_class"]
    response = client.post(f"{base}/api/v1/ask", json=body, timeout=120.0)
    payload = response.json() if response.headers.get(
        "content-type", "",
    ).startswith("application/json") else {"raw": response.text}
    answer = str(payload.get("answer", ""))
    state = str(payload.get("state", ""))
    lowered = answer.lower()
    failures: list[str] = []
    if response.status_code != 200:
        failures.append(f"http {response.status_code}")
    if state != case["expect"]:
        failures.append(f"state {state!r} khác kỳ vọng {case['expect']!r}")
    for needle in case["must"]:
        if needle.lower() not in lowered:
            failures.append(f"thiếu {needle!r}")
    for needle in case["must_not"]:
        if needle.lower() in lowered:
            failures.append(f"có chuỗi cấm {needle!r}")
    return {
        "id": case["id"],
        "severity": case["severity"],
        "use_class": case["use_class"],
        "question": case["q"],
        "note": case["note"],
        "http_status": response.status_code,
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

    selected = [
        case for case in CASES
        if not args.only or case["id"] in {item.strip() for item in args.only.split(",")}
    ]
    with httpx.Client(follow_redirects=False, timeout=60.0) as client:
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
    failed_p0 = [item for item in results if item["verdict"] == "FAIL" and item["severity"] == "P0"]
    failed_p1 = [item for item in results if item["verdict"] == "FAIL" and item["severity"] == "P1"]
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
