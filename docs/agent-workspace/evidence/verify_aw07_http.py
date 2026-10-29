"""Contractor self-service/diagnostic and bounded-load probe. Synthetic only.

The only permitted destination is the isolated loopback product API. Creates and
deletes its own test workspaces; never reads another catalogue or provider key.
"""
import concurrent.futures
import json
import statistics
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8130/api/workspace"
ORIGIN = "http://127.0.0.1:3130"


def main():
    started = time.perf_counter()
    def key():
        return str(uuid.uuid4())
    created, checks = [], []
    with httpx.Client(base_url=BASE, headers={"origin": ORIGIN}, timeout=20) as client:
        def get(path):
            response = client.get(path)
            assert response.is_success, (path, response.status_code)
            return response.json()

        def post(path, data):
            response = client.post(path, json=data)
            assert response.is_success, (path, response.status_code, response.text[:300])
            return response.json()

        def create(label):
            wid = post("/workspaces", dict(name=label))["id"]
            created.append(wid)
            return wid

        def run(wid):
            tick = time.perf_counter()
            rid = post("/runs", dict(workspace_id=wid, message="fixture:chat", client_request_id=key()))["run_id"]
            until = time.monotonic() + 25
            while time.monotonic() < until:
                row = get("/runs/" + rid)
                if row["state"] == "completed":
                    return dict(completed_ms=round((time.perf_counter() - tick) * 1000, 3))
                assert row["state"] not in {"failed", "cancelled"}, row
                time.sleep(.02)
            raise AssertionError("bounded mock run timed out")

        post("/session", {})
        readiness = get("/readiness")
        assert readiness["available"] and readiness["test_mode"]
        initial = get("/diagnostics")
        assert initial["format"] == "agent-workspace-diagnostics-v1"
        canary = "PRIVATE_SYNTHETIC_CANARY_" + key().replace("-", "")
        try:
            wid = create(canary + " project")
            source = post(f"/workspaces/{wid}/files", dict(filename=canary + ".txt", content=canary + " source text, station008291,71.625mm.", media_type="text/plain"))
            post(f"/workspaces/{wid}/memory", dict(content=canary + " memory", request_id=key()))
            post(f"/workspaces/{wid}/brief", dict(goal=canary + " goal", decisions="Keep synthetic originals.", remaining="Test diagnostic privacy.", expected_revision=0, request_id=key()))
            output = post(f"/workspaces/{wid}/artifacts", dict(title=canary + " artifact", kind="document", content="# " + canary + "\n\n008291 and71.625mm.\n", request_id=key()))
            post(f"/artifacts/{output['id']}/revisions", dict(expected_version=1, content="# " + canary + " v2\n\n008291 and71.625mm.\n", request_id=key()))
            diag = get("/diagnostics")
            encoded = json.dumps(diag)
            for private in (canary, wid, source["id"], output["id"], "/Users/", "workspace_session", "api_key", "token_hash"):
                assert private not in encoded, private
            assert len(encoded.encode()) < 32000
            with httpx.Client(base_url=BASE, headers={"origin": ORIGIN}, timeout=15) as other:
                assert other.get("/diagnostics").status_code == 401
                other.post("/session", json={}).raise_for_status()
                before_other = other.get("/diagnostics").json()
                own_before = get("/diagnostics")
                result = other.post("/workspaces", json={"name": "Foreign synthetic only"})
                result.raise_for_status()
                foreign = result.json()
                assert get("/diagnostics") == own_before
                assert other.get("/diagnostics").json() != before_other
                preview = other.get(f"/workspaces/{foreign['id']}/delete-preview").json()
                other.post(f"/workspaces/{foreign['id']}/delete", json=dict(confirmation_token=preview["confirmation_token"], confirm_name=preview["name"], request_id=key())).raise_for_status()
            checks.append("authenticated allowlisted diagnostics omit private canaries and other-owner counts")
            spaces = [wid] + [create("AW07 root synthetic parallel " + str(number)) for number in range(3)]
            completions = []
            for _ in range(2):
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                    completions.extend(pool.map(run, spaces))
            checks.append("eight scripted runs, two batches of four independent workspaces, all completed")
            latencies = []
            for _ in range(15):
                tick = time.perf_counter()
                get("/diagnostics")
                latencies.append((time.perf_counter() - tick) * 1000)
            source_read = get(f"/files/{source['id']}")
            assert canary in source_read["content"]
            assert get(f"/artifacts/{output['id']}?version=1")["content"].startswith("# " + canary)
            assert get(f"/artifacts/{output['id']}")["version"] == 2
            checks.append("bounded parallel mock activity preserves unrelated source bytes and both manual versions")
            result = dict(status="PASS", date="2026-10-29", provenance="Contractor real loopback API and product storage/DBOS with explicit scripted model; not natural AI or human review", checks=checks,
                measurements=dict(mock_runs=8, concurrency=4, batches=2, mock_completion_ms_median=round(statistics.median(r["completed_ms"] for r in completions), 3), mock_completion_ms_max=max(r["completed_ms"] for r in completions), first_useful_output_ms=None, first_useful_output_note="Not measured by this polling probe; completion is a synthetic transport result, not useful AI output.", diagnostic_samples=len(latencies), diagnostic_ms_median=round(statistics.median(latencies), 3), diagnostic_ms_max=round(max(latencies), 3)),
                limitations=["Warm small local samples do not certify capacity, provider latency tail or deployment.", "Simulated completion is not semantic quality, actual bill or human productivity.", "Per-owner aggregates remain metadata; report is not anonymous telemetry or automatic upload."],
                external_calls=0, real_ai_acceptance="NOT_MEASURED", elapsed_seconds=round(time.perf_counter() - started, 3))
        finally:
            for wid in reversed(created):
                preview = get(f"/workspaces/{wid}/delete-preview")
                assert preview["blocked_reason"] is None
                post(f"/workspaces/{wid}/delete", dict(confirmation_token=preview["confirmation_token"], confirm_name=preview["name"], request_id=key()))
        result["own_workspaces_created_and_deleted"] = len(created)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
