"""Contractor's synthetic loopback proof, not a real-AI evaluation.

Creates/deletes only workspaces it owns on the isolated AW-06 test runtime.
No provider/network endpoint other than the declared loopback API is accepted.
"""
import base64
import json
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8130/api/workspace"
ORIGIN = "http://127.0.0.1:3130"


def main():
    started = time.perf_counter()
    key = lambda: str(uuid.uuid4())
    created, checks, measurements = [], [], {}
    with httpx.Client(base_url=BASE, headers={"origin": ORIGIN}, timeout=20) as client:
        def post(path, data):
            response = client.post(path, json=data)
            assert response.is_success, (path, response.status_code, response.text[:1000])
            return response.json()

        def get(path):
            response = client.get(path)
            assert response.is_success, (path, response.status_code, response.text[:1000])
            return response.json()

        def space(name):
            wid = post("/workspaces", {"name": "AW06 root synthetic " + name})["id"]
            created.append(wid)
            return wid

        def wait(rid, expected="completed"):
            until = time.monotonic() + 25
            while time.monotonic() < until:
                row = get("/runs/" + rid)
                if row["state"] in {"completed", "failed", "cancelled"}:
                    assert row["state"] == expected, row
                    return row
                time.sleep(.05)
            raise AssertionError("bounded simulation deadline exceeded")

        def start(wid, message, context=None, request_id=None):
            body = dict(workspace_id=wid, message=message, client_request_id=request_id or key())
            if context is not None:
                body["context"] = context
            return post("/runs", body)["run_id"]

        def reference(file):
            return dict(kind="file", id=file["id"])

        post("/session", {})
        ready = get("/readiness")
        assert ready["available"] and ready["test_mode"]
        try:
            wid = space("weather notebook")
            old = post(f"/workspaces/{wid}/files", dict(filename="weather-old.txt", content="Synthetic station 008291; rainfall 71.625 mm.\n", media_type="text/plain"))
            new = post(f"/workspaces/{wid}/files", dict(filename="weather-new.txt", content="Synthetic station 008291; rainfall 73.875 mm.\n", media_type="text/plain"))
            unrelated = post(f"/workspaces/{wid}/files", dict(filename="library.txt", content="Synthetic library code L-006: 152 books.\n", media_type="text/plain"))
            brief_body = dict(goal="Compare synthetic weather notes.", decisions="Keep reported values distinct.", remaining="Review the newer measurement.", expected_revision=0, request_id=key())
            brief = post(f"/workspaces/{wid}/brief", brief_body)
            assert brief["revision"] == 1 and brief["source"] == "user"
            assert post(f"/workspaces/{wid}/brief", brief_body) == brief
            assert client.post(f"/workspaces/{wid}/brief", json=brief_body | {"request_id": key()}).status_code == 409
            checks.append("user brief CAS, reload and lost-ACK identity")
            options = dict(references=[reference(old)], target=None)
            preview = post(f"/workspaces/{wid}/context-preview", dict(message="fixture:create", **options))
            assert preview["references"] == options["references"]
            assert preview["context_bytes"] <= preview["limit_bytes"]
            assert "71.625" in preview["selections"][0]["content"]
            assert get(f"/workspaces/{wid}/search?q=008291")["items"]
            measurements["one_source_preview_bytes"] = preview["context_bytes"]
            request_id = key()
            rid = start(wid, "fixture:create", options, request_id)
            wait(rid)
            assert start(wid, "fixture:create", options, request_id) == rid
            altered = dict(workspace_id=wid, message="fixture:create", client_request_id=request_id, context=dict(references=[reference(new)], target=None))
            assert client.post("/runs", json=altered).status_code == 409
            actual = get(f"/runs/{rid}/context")
            assert actual["references"] == options["references"] and actual["read_ledger"]
            assert all(type(read["end"]) is int for read in actual["read_ledger"])
            output = get(f"/workspaces/{wid}/artifacts")["items"][0]
            first_content = get(f"/artifacts/{output['id']}?version=1")["content"]
            deps = get(f"/artifacts/{output['id']}/dependencies?version=1")
            assert deps["status"] == "known" and not deps["stale"]
            checks.append("explicit context, actual read ranges and context-bound run idempotency")
            second_run = start(wid, "fixture:create", dict(references=[reference(unrelated)], target=None))
            wait(second_run)
            other = next(a for a in get(f"/workspaces/{wid}/artifacts")["items"] if a["id"] != output["id"])
            post(f"/workspaces/{wid}/source-replacements", dict(old_file_id=old["id"], new_file_id=new["id"], request_id=key()))
            assert get(f"/artifacts/{output['id']}/dependencies?version=1")["stale"]
            assert not get(f"/artifacts/{other['id']}/dependencies?version=1")["stale"]
            original = client.get(f"/files/{old['id']}/download")
            assert original.is_success and b"71.625" in original.content
            checks.append("affected-only source freshness and immutable original")
            target = dict(kind="artifact", id=output["id"], version=1)
            edit_run = start(wid, "fixture:edit", dict(references=[reference(new)], target=target))
            wait(edit_run)
            assert get(f"/artifacts/{output['id']}")["version"] == 2
            assert get(f"/artifacts/{output['id']}?version=1")["content"] == first_content
            checks.append("continue exact output revision, immutable previous version")
            with httpx.Client(base_url=BASE, headers={"origin": ORIGIN}, timeout=15) as stranger:
                stranger.post("/session", json={}).raise_for_status()
                assert stranger.get(f"/runs/{rid}/context").status_code == 404
                assert stranger.get(f"/workspaces/{wid}/brief").status_code == 404
            foreign = space("other scope")
            denied = client.post(f"/workspaces/{foreign}/context-preview", json=dict(message="fixture:chat", **options))
            assert denied.status_code == 404
            checks.append("owner and same-owner cross-workspace reference isolation")
            snapshot = client.get(f"/workspaces/{wid}/export")
            snapshot.raise_for_status()
            import_body = dict(archive_base64=base64.b64encode(snapshot.content).decode(), name="AW06 root synthetic restored", include_memory=False)
            confirm = post("/imports/preview", import_body)
            restored = post("/imports/commit", import_body | dict(confirmation_token=confirm["confirmation_token"], request_id=key()))
            restored_id = restored["workspace"]["id"]
            created.append(restored_id)
            assert get(f"/workspaces/{restored_id}/brief")["goal"] == brief["goal"]
            archived = get(f"/workspaces/{restored_id}/messages")["items"]
            assert archived and all(row["run_id"] is None for row in archived)
            restored_preview = post(f"/workspaces/{restored_id}/context-preview", dict(message="fixture:chat", references=[], target=None))
            assert restored_preview["recent_messages"] == []
            checks.append("portable user brief and non-executable archived dialogue")
            cancelled = start(foreign, "fixture:slow")
            post(f"/runs/{cancelled}/cancel", {})
            wait(cancelled, "cancelled")
            checks.append("new workflow cancellation remains bounded")
        finally:
            for wid in reversed(created):
                preview = get(f"/workspaces/{wid}/delete-preview")
                assert preview["blocked_reason"] is None, preview
                post(f"/workspaces/{wid}/delete", dict(confirmation_token=preview["confirmation_token"], confirm_name=preview["name"], request_id=key()))
        print(json.dumps(dict(status="PASS", provenance="Contractor real loopback HTTP, deterministic synthetic model; not AI semantic evidence", checks=checks, workspaces_created_and_deleted=len(created), measurements=measurements, elapsed_seconds=round(time.perf_counter() - started, 3), external_calls=0, real_ai_acceptance="NOT_MEASURED"), indent=2))


if __name__ == "__main__":
    main()
