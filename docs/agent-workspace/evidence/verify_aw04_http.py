"""Contractor proof on the real loopback API; synthetic disposable data only.

Requires simulation readiness. Does not call external models or retain cookies.
Prints evidence, including a bounded 100-read probe, rather than claiming model
capacity or semantic quality from deterministic fixtures.
"""
import concurrent.futures
import hashlib
import io
import json
import platform
import time
import uuid
import zipfile

import httpx


BASE = "http://127.0.0.1:8110/api/workspace"
HEADERS = {"origin": "http://127.0.0.1:3110"}


def main():
    started = time.monotonic()
    key = lambda: str(uuid.uuid4())
    with httpx.Client(base_url=BASE, headers=HEADERS, timeout=15) as client:
        def post(path, body=None):
            response = client.post(path, json=body or {})
            response.raise_for_status()
            return response.json()

        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def delete(path, name):
            preview = get(path + "/delete-preview")
            body = dict(request_id=key(), confirmation_token=preview["confirmation_token"], confirm_name=name)
            return post(path + "/delete", body), body

        post("/session")
        ready = get("/readiness")
        assert ready["test_mode"] is True and ready["available"] is True, ready
        name = "AW04 disposable contractor proof " + key()[:8]
        wid = post("/workspaces", {"name": name})["id"]
        path = "/workspaces/" + wid
        other_name = name + " retained control"
        other_id = post("/workspaces", {"name": other_name})["id"]
        other_path = "/workspaces/" + other_id
        # Identifiers/zeroes/Unicode survive original byte export exactly.
        raw = "batch,quantity,note\n004173,91.125,Tiếng Việt\n".encode()
        source = post(path + "/files", dict(filename="source.csv", content=raw.decode()))
        aid = post(path + "/artifacts", dict(title="Synthetic brief", kind="document",
            content="# Draft\n\nBatch 004173, quantity 91.125.\n", request_id=key()))["id"]
        post("/artifacts/" + aid + "/revisions", dict(expected_version=1,
            content="# Revised\n\nBatch 004173, quantity 91.125, unchanged.\n", request_id=key()))
        post(path + "/memory", dict(content="Synthetic explicit preference only.", request_id=key()))
        response = client.get(path + "/export")
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            index = json.loads(archive.read("sources/index.json"))
            assert archive.read(index[0]["original_path"]) == raw
            assert len([p for p in archive.namelist() if p.startswith("artifacts/") and p.endswith(".txt")]) == 2
            for entry in manifest["entries"]:
                content = archive.read(entry["path"])
                assert len(content) == entry["bytes"]
                assert hashlib.sha256(content).hexdigest() == entry["sha256"]
            assert all(".." not in p.split("/") and not p.startswith("/") for p in archive.namelist())
            assert not any(p.endswith(".sqlite") for p in archive.namelist())
            assert "session" not in manifest and "api_key" not in manifest
            export_members = len(archive.namelist())
        # A different owner cannot preview/export/delete this disposable scope.
        with httpx.Client(base_url=BASE, headers=HEADERS) as foreign:
            foreign.post("/session", json={}).raise_for_status()
            assert foreign.get(path + "/delete-preview").status_code == 404
            assert foreign.get(path + "/export").status_code == 404
        preview = get(path + "/delete-preview")
        stale_body = dict(request_id=key(), confirmation_token=preview["confirmation_token"], confirm_name=name)
        post(path + "/files", dict(filename="later.txt", content="Synthetic change after preview."))
        assert client.post(path + "/delete", json=stale_body).status_code == 409
        preview = get(path + "/delete-preview")
        bad_body = dict(request_id=key(), confirmation_token=preview["confirmation_token"], confirm_name=name + "wrong")
        assert client.post(path + "/delete", json=bad_body).status_code == 400

        # Same-host HTTP read latency only. Four callers share one test session,
        # 100 requests total, no model dispatch; no extrapolation to AI capacity.
        samples = []
        def read_one(i):
            before = time.perf_counter()
            target = path + "/files" if i % 2 else "/status"
            r = client.get(target)
            r.raise_for_status()
            return (time.perf_counter() - before) * 1000
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            samples = sorted(pool.map(read_one, range(100)))
        result, delete_body = delete(path, name)
        assert post(path + "/delete", delete_body) == result
        assert client.post(other_path + "/delete", json=delete_body).status_code == 409
        for target in (path + "/messages", path + "/files", path + "/memory", path + "/export",
            path + "/delete-preview", "/artifacts/" + aid, "/files/" + source["id"]):
            assert client.get(target).status_code == 404, target
        assert get(other_path + "/files") == {"items": []}
        assert wid not in {w["id"] for w in get("/workspaces")["items"]}
        delete(other_path, other_name)
        print(json.dumps(dict(status="PASS", lane="actual local HTTP, simulation runtime",
            external_model_calls=0, semantic_quality="NOT_MEASURED", export_members=export_members,
            export_original_bytes_exact=True, export_hashes_verified=True,
            stale_confirmation_rejected=True, lost_ack_delete_idempotent=True,
            deleted_resources_inaccessible=True, unrelated_workspace_preserved=True,
            created_disposable_workspaces=2, deleted_disposable_workspaces=2,
            read_probe=dict(n=100, concurrency=4, p50_ms=round(samples[49], 3),
                p95_ms=round(samples[94], 3), p99_ms=round(samples[98], 3), max_ms=round(samples[-1], 3),
                scope="50 status + 50 files GETs, tiny synthetic workspace; not model latency/capacity"),
            machine=dict(os=platform.system(), release=platform.release(), architecture=platform.machine()),
            duration_seconds=round(time.monotonic() - started, 3)), indent=2))


if __name__ == "__main__":
    main()
