#!/usr/bin/env python3
"""TIP-050.P · dò tìm nguyên nhân: xếp hạng hỏng hay thu hồi hỏng.

Lượt chạy 21/09 cho thấy 7 trong 16 câu hỏi được trả lời bằng `L3F.ENT.001`,
tức bản ghi tên pháp nhân, và vẫn mang nhãn `grounded`. Script này tách hai giả
thuyết bằng cách đi thẳng vào `/api/v1/search`, nơi không có tầng dựng câu:

- Nếu bản ghi đúng CÓ trong kết quả nhưng thua điểm: lỗi xếp hạng.
- Nếu bản ghi đúng KHÔNG có mặt: lỗi thu hồi hoặc lỗi đánh chỉ mục.

Phần hai cô lập cổng `use_class` của TIP-050 bằng một câu neo từ vựng hiếm
(`Argon2id`), để cổng nhận được đúng loại bản ghi mà nó sinh ra để chặn.

Chỉ dùng thư viện chuẩn.

    python3 eval/tip050/probe_retrieval.py --base http://127.0.0.1:18000
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

#: (nhãn, truy vấn, bản ghi kỳ vọng phải có mặt trong kết quả)
SEARCH_PROBES: list[tuple[str, str, str]] = [
    ("P1", "HeraSight Standard NETD", "SPEC.HERASIGHT.STD.NETD"),
    ("P2", "HeraSight Standard có độ nhạy nhiệt NETD bao nhiêu?", "SPEC.HERASIGHT.STD.NETD"),
    ("P3", "NETD 40 mK", "SPEC.HERASIGHT.STD.NETD"),
    ("P4", "VEGA RTK tích hợp sẵn", "SPEC.VEGA.RTK"),
    ("P5", "VEGA có RTK tích hợp sẵn hay chỉ tương thích?", "SPEC.VEGA.RTK"),
    ("P6", "quy ước đánh số phiên bản phần cứng", "L3F.STD.001"),
    ("P7", "Argon2id", "L3F.INF.014"),
    ("P8", "Mật khẩu người dùng được băm bằng thuật toán nào?", "L3F.INF.014"),
    ("P9", "us-east-1", "L3F.INF.002"),
    ("P10", "Dữ liệu của RtR được lưu ở đâu?", "L3F.INF.002"),
    ("P11", "SOC 2", ""),
    ("P12", "RtR có chứng nhận SOC 2 không?", ""),
]

#: Cặp cô lập cổng use_class: cùng câu hỏi, hai ngữ cảnh.
GATE_PROBES: list[tuple[str, str, str]] = [
    ("G1", "Mật khẩu người dùng của RtR được băm bằng Argon2id phải không?", "proposal"),
    ("G2", "Mật khẩu người dùng của RtR được băm bằng Argon2id phải không?", "attestation"),
    ("G3", "Argon2id được RtR dùng để làm gì?", "proposal"),
    ("G4", "Argon2id được RtR dùng để làm gì?", "attestation"),
    # DA-003 của TIP-051: cổng chống sửa quá tay. Câu hỏi định nghĩa thật thì
    # bản ghi tên pháp nhân VẪN phải là câu trả lời.
    ("G5", "RtR là công ty gì?", "proposal"),
]


#: PHẦN 3 · kiểm giả thuyết "tên chuẩn bị nối thêm vào truy vấn".
#: `plan_query` kết thúc bằng `_augment_with(retrieval_base, [*entities, ...])`,
#: nối TÊN CHUẨN của thực thể vào cuối câu hỏi khi tên đó chưa có mặt. Với mọi
#: câu nhắc "RtR", nhánh từ vựng thực ra nhận "câu hỏi + Real-time Robotics",
#: nên bản ghi nào mang tên đầy đủ đó đều được cộng điểm, kể cả khi nội dung
#: không liên quan. `/search` không đi qua bước này, nên hai bên lệch nhau.
#: Mỗi cặp dưới đây là cùng một câu hỏi, dạng gốc và dạng đã nối tên chuẩn.
DILUTION_PROBES: list[tuple[str, str, str]] = [
    (
        "D1 gốc",
        "Argon2id được RtR dùng để làm gì?",
        "L3F.INF.014",
    ),
    (
        "D1 nối tên chuẩn",
        "Argon2id được RtR dùng để làm gì? Real-time Robotics",
        "L3F.INF.014",
    ),
    (
        "D2 gốc",
        "Mật khẩu người dùng của RtR được băm bằng Argon2id phải không?",
        "L3F.INF.014",
    ),
    (
        "D2 nối tên chuẩn",
        "Mật khẩu người dùng của RtR được băm bằng Argon2id phải không? "
        "Real-time Robotics",
        "L3F.INF.014",
    ),
    (
        "D3 gốc",
        "Dữ liệu của RtR được lưu ở đâu?",
        "L3F.INF.002",
    ),
    (
        "D3 nối tên chuẩn",
        "Dữ liệu của RtR được lưu ở đâu? Real-time Robotics",
        "L3F.INF.002",
    ),
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Client:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            NoRedirect(),
        )

    def _send(self, request: urllib.request.Request) -> tuple[int, Any, bytes]:
        try:
            with self.opener.open(request, timeout=180) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def get(self, url: str) -> tuple[int, Any, bytes]:
        return self._send(urllib.request.Request(url, headers={"Accept": "application/json"}))

    def post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, Any, bytes]:
        return self._send(urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        ))


def login(client: Client, base: str, email: str, sub: str) -> dict[str, Any]:
    _, headers, _ = client.get(f"{base}/auth/login")
    first = urlparse(headers["Location"]).query
    _, headers, _ = client.get(f"{base}/auth/dev/authorize?{first}&email={email}&sub={sub}")
    second = urlparse(headers["Location"]).query
    client.get(f"{base}/auth/callback?{second}")
    status, _, body = client.get(f"{base}/auth/me")
    if status != 200:
        raise RuntimeError(f"auth/me trả {status}")
    return dict(json.loads(body))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18000")
    parser.add_argument("--email", default="staff@rtrobotics.com")
    parser.add_argument("--sub", default="dev-staff")
    parser.add_argument("--out", default="eval/tip050/probe_retrieval.json")
    args = parser.parse_args()

    client = Client()
    try:
        login(client, args.base, args.email, args.sub)
    except Exception as error:  # noqa: BLE001
        print(f"Không đăng nhập được vào {args.base}: {error}")
        return 2

    record: dict[str, Any] = {"search": [], "gate": []}
    print("\n" + "=" * 78)
    print("PHẦN 1 · XẾP HẠNG THU HỒI (đi thẳng /search, không qua tầng dựng câu)")
    print("=" * 78)
    for label, query, expected in SEARCH_PROBES:
        status, _, raw = client.post_json(
            f"{args.base}/api/v1/search",
            {"query": query, "top_k": 6},
        )
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"results": []}
        rows = payload.get("results", [])
        keys = [row["citation"]["record_key"] for row in rows]
        if expected:
            if expected in keys:
                verdict = f"CÓ MẶT ở hạng {keys.index(expected) + 1}"
            else:
                verdict = "VẮNG MẶT"
        else:
            verdict = "không có bản ghi kỳ vọng"
        print(f"\n{label} [{status}] {query!r}")
        print(f"   kỳ vọng {expected or '(không)'}: {verdict}")
        for rank, row in enumerate(rows, 1):
            citation = row["citation"]
            print(
                f"   {rank}. {citation['record_key']:32} "
                f"lex={row['lexical_score']:.4f} vec={row['vector_score']:.4f} "
                f"fusion={row['fusion_score']:.4f}",
            )
        record["search"].append({
            "label": label, "query": query, "expected": expected,
            "http_status": status, "verdict": verdict,
            "results": [
                {
                    "record_key": row["citation"]["record_key"],
                    "provenance_level": row["citation"]["provenance_level"],
                    "lexical_score": row["lexical_score"],
                    "vector_score": row["vector_score"],
                    "fusion_score": row["fusion_score"],
                }
                for row in rows
            ],
        })

    print("\n" + "=" * 78)
    print("PHẦN 2 · CÔ LẬP CỔNG use_class (câu neo từ vựng hiếm)")
    print("=" * 78)
    for label, question, use_class in GATE_PROBES:
        status, _, raw = client.post_json(
            f"{args.base}/api/v1/ask",
            {"question": question, "use_class": use_class},
        )
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        cites = [
            (item.get("record_key"), item.get("provenance_level"))
            for item in payload.get("citations", [])
        ]
        print(f"\n{label} [{status}] ngữ cảnh={use_class}")
        print(f"   hỏi: {question}")
        print(f"   state={payload.get('state')} reason={payload.get('reason_code')}")
        print(f"   citations: {cites or '-'}")
        print(f"   trả lời: {str(payload.get('answer', ''))[:220]}")
        record["gate"].append({
            "label": label, "question": question, "use_class": use_class,
            "http_status": status, "state": payload.get("state"),
            "reason_code": payload.get("reason_code"),
            "answer": payload.get("answer", ""), "citations": cites,
        })

    print("\n" + "=" * 78)
    print("PHẦN 3 · GIẢ THUYẾT NHÂN ĐÔI CÂU HỎI (cùng câu, hai dạng, đi /search)")
    print("=" * 78)
    record["dilution"] = []
    for label, query, expected in DILUTION_PROBES:
        status, _, raw = client.post_json(
            f"{args.base}/api/v1/search",
            {"query": query, "top_k": 5},
        )
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"results": []}
        rows = payload.get("results", [])
        keys = [row["citation"]["record_key"] for row in rows]
        rank = keys.index(expected) + 1 if expected in keys else 0
        print(f"\n{label} [{status}] hạng của {expected}: {rank or 'VẮNG MẶT'}")
        for order, row in enumerate(rows, 1):
            print(
                f"   {order}. {row['citation']['record_key']:32} "
                f"lex={row['lexical_score']:.4f} fusion={row['fusion_score']:.4f}",
            )
        record["dilution"].append({
            "label": label, "query": query, "expected": expected, "rank": rank,
            "results": [
                {
                    "record_key": row["citation"]["record_key"],
                    "lexical_score": row["lexical_score"],
                    "fusion_score": row["fusion_score"],
                }
                for row in rows
            ],
        })

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    print(f"\nBản ghi đầy đủ: {args.out}")
    print(
        "\nĐọc kết quả: PHẦN 1 vắng mặt nghĩa là lỗi thu hồi hoặc chỉ mục; "
        "có mặt nhưng hạng thấp nghĩa là lỗi xếp hạng.\n"
        "PHẦN 2: G1/G3 phải grounded trên L3F.INF.014, G2/G4 phải honest_null "
        "nêu ngữ cảnh chứng thực, G5 phải VẪN trích L3F.ENT.001 vì đó là câu "
        "hỏi định nghĩa thật. G5 hỏng nghĩa là TIP-051 sửa quá tay.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
