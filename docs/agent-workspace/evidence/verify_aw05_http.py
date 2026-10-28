"""Contractor proof against AW-05 isolated synthetic loopback runtime only.

No credentials or user catalogue. Model is an explicitly checked simulation.
Output is measured local behavior, not AI semantic/productivity certification.
"""
import base64
import hashlib
import io
import json
import time
import uuid
import zipfile

import httpx

BASE = "http://127.0.0.1:8120/api/workspace"
ORIGIN = "http://127.0.0.1:3120"


def main():
    started = time.perf_counter()
    key = lambda: str(uuid.uuid4())
    with httpx.Client(base_url=BASE, headers={"origin": ORIGIN}, timeout=15) as client:
        def post(path, body=None):
            r = client.post(path, json=body or {})
            r.raise_for_status()
            return r.json()

        def get(path):
            r = client.get(path)
            r.raise_for_status()
            return r.json()

        def exported(wid):
            r = client.get(f"/workspaces/{wid}/export")
            r.raise_for_status()
            return r.content

        def entries(raw):
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                return {p: z.read(p) for p in z.namelist()}

        def run(wid):
            rid = post("/runs", dict(workspace_id=wid, message="fixture:chat", client_request_id=key()))["run_id"]
            until = time.monotonic() + 15
            while time.monotonic() < until:
                item = get("/runs/" + rid)
                if item["state"] == "completed":
                    return rid
                assert item["state"] not in {"failed", "cancelled"}, item
                time.sleep(.03)
            raise AssertionError("simulation run did not finish")

        post("/session")
        ready = get("/readiness")
        assert ready["available"] is True and ready["test_mode"] is True
        original = post("/workspaces", {"name": "Synthetic museum continuity " + key()[:8]})
        wid = original["id"]
        raw = "id,quantity,note\r\n004173,91.125,Tiếng Việt Δ\r\n".encode()
        source = post(f"/workspaces/{wid}/files", dict(filename="loans.csv", content=raw.decode()))
        artifact = post(f"/workspaces/{wid}/artifacts", dict(title="Museum loan brief", kind="document",
            content="# Original\n\nLoan 004173: quantity 91.125.\n", request_id=key()))
        post(f"/artifacts/{artifact['id']}/revisions", dict(expected_version=1,
            content="# Revised\n\nLoan 004173: quantity 91.125.\n", request_id=key()))
        memory = post(f"/workspaces/{wid}/memory", dict(content="Synthetic museum preference, not authority.", request_id=key()))
        post(f"/workspaces/{wid}/schedules", dict(message="fixture:chat", due_at=120, request_id=key()))
        run(wid)
        messages = get(f"/workspaces/{wid}/messages")["items"]
        snapshot = exported(wid)
        archive = base64.b64encode(snapshot).decode()
        body = dict(archive_base64=archive, name="Museum restored without memory", include_memory=False)
        t = time.perf_counter()
        preview = post("/imports/preview", body)
        preview_ms = (time.perf_counter() - t) * 1000
        assert preview["counts"]["versions"] == 2
        assert preview["counts"]["memory_selected"] == 0
        assert preview["counts"]["schedules_omitted"] == 1
        before = len(get("/workspaces")["items"])
        request = body | dict(confirmation_token=preview["confirmation_token"], request_id=key())
        assert client.post("/imports/commit", json=request | {"include_memory": True}).status_code == 409
        with httpx.Client(base_url=BASE, headers={"origin": ORIGIN}) as stranger:
            stranger.post("/session", json={}).raise_for_status()
            assert stranger.post("/imports/commit", json=request).status_code == 409
        t = time.perf_counter()
        restored = post("/imports/commit", request)
        commit_ms = (time.perf_counter() - t) * 1000
        clone = restored["workspace"]
        cid = clone["id"]
        assert post("/imports/commit", request) == restored
        assert len(get("/workspaces")["items"]) == before + 1
        assert client.post("/imports/commit", json=request | {"name": "different"}).status_code == 409
        files = get(f"/workspaces/{cid}/files")["items"]
        assert files[0]["id"] != source["id"]
        assert client.get(f"/files/{files[0]['id']}/download").content == raw
        outputs = get(f"/workspaces/{cid}/artifacts")["items"]
        aid = outputs[0]["id"]
        assert aid != artifact["id"]
        for version in (1, 2):
            assert get(f"/artifacts/{aid}?version={version}")["content"] == get(f"/artifacts/{artifact['id']}?version={version}")["content"]
        copied_messages = get(f"/workspaces/{cid}/messages")["items"]
        assert [(m["role"], m["content"]) for m in copied_messages] == [(m["role"], m["content"]) for m in messages]
        assert all(m["run_id"] is None for m in copied_messages)
        assert get(f"/workspaces/{cid}/memory")["items"] == []
        assert get(f"/workspaces/{cid}/schedules")["items"] == []
        assert get(f"/workspaces/{cid}/connection")["enabled"] is False
        assert get(f"/workspaces/{cid}/approvals")["items"] == []
        lineage = get(f"/workspaces/{cid}/import-lineage")
        assert lineage["archive_sha256"] == hashlib.sha256(snapshot).hexdigest()
        post(f"/artifacts/{aid}/revisions", dict(expected_version=2, content="# Third\n\nStill 004173 and 91.125.\n", request_id=key()))
        archived = post(f"/workspaces/{cid}/metadata", dict(expected_revision=clone["revision"], archived=True, request_id=key()))
        assert cid not in {w["id"] for w in get("/workspaces")["items"]}
        assert cid in {w["id"] for w in get("/workspaces?include_archived=true")["items"]}
        assert client.post("/runs", json=dict(workspace_id=cid, message="fixture:chat", client_request_id=key())).status_code == 409
        renamed = post(f"/workspaces/{cid}/metadata", dict(expected_revision=archived["revision"], name="Restored museum project", request_id=key()))
        assert client.post(f"/workspaces/{cid}/metadata", json=dict(expected_revision=1, archived=False, request_id=key())).status_code == 409
        post(f"/workspaces/{cid}/metadata", dict(expected_revision=renamed["revision"], archived=False, request_id=key()))
        assert len(get("/workspaces?q=restored%20MUSEUM")["items"]) == 1
        second_body = dict(archive_base64=base64.b64encode(exported(cid)).decode(), name="Second generation museum", include_memory=True)
        second_preview = post("/imports/preview", second_body)
        second = post("/imports/commit", second_body | dict(confirmation_token=second_preview["confirmation_token"], request_id=key()))["workspace"]
        sid = second["id"]
        second_artifact = get(f"/workspaces/{sid}/artifacts")["items"][0]
        assert len(get(f"/artifacts/{second_artifact['id']}/versions")["items"]) == 3
        assert get(f"/artifacts/{artifact['id']}")["version"] == 2
        assert get(f"/workspaces/{wid}/memory")["items"][0]["id"] == memory["id"]
        # This copy opts in to the ORIGINAL snapshot memory, not deleted/cache data.
        opt_body = body | dict(name="Museum explicit memory restore", include_memory=True)
        opt_preview = post("/imports/preview", opt_body)
        opt = post("/imports/commit", opt_body | dict(confirmation_token=opt_preview["confirmation_token"], request_id=key()))["workspace"]
        copied_memory = get(f"/workspaces/{opt['id']}/memory")["items"]
        assert copied_memory[0]["content"] == "Synthetic museum preference, not authority."
        assert copied_memory[0]["id"] != memory["id"]
        assert entries(snapshot)["sources/" + source["id"] + "/original"] == raw
        for space in (original, clone, second, opt):
            p = f"/workspaces/{space['id']}"
            confirm = get(p + "/delete-preview")
            post(p + "/delete", dict(confirm_name=confirm["name"], confirmation_token=confirm["confirmation_token"], request_id=key()))
        assert client.post("/imports/commit", json=request).status_code == 404
        print(json.dumps(dict(status="PASS", evidence_kind="actual isolated local HTTP and SQLite; deterministic model",
            external_model_calls=0, archive_bytes=len(snapshot), sources=1, artifact_versions_original=2,
            artifact_versions_second_generation=3, display_messages=len(messages), original_bytes_exact=True,
            identity_remapped=True, no_restored_authority=True, memory_opt_in_checked=True,
            wrong_owner_and_changed_choices_rejected=True, idempotent_import=True,
            archive_search_rename_cas=True, deleted_import_cannot_resurrect=True,
            created_disposable_workspaces=4, deleted_disposable_workspaces=4,
            preview_ms=round(preview_ms, 3), commit_ms=round(commit_ms, 3),
            duration_seconds=round(time.perf_counter() - started, 3), semantic_quality="NOT_MEASURED"), indent=2))


if __name__ == "__main__":
    main()
