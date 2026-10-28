"""Contractor synthetic smoke against the actual loopback AW-03 API.

Creates two small verification workspaces. Requires simulation mode, never
deletes unrelated data, calls no external provider or live connector.
"""
import json
import time
import uuid

import httpx


def main():
    base = "http://127.0.0.1:8110/api/workspace"
    with httpx.Client(base_url=base, headers={"origin": "http://127.0.0.1:3110"}, timeout=10) as c:
        def key():
            return str(uuid.uuid4())

        def post(path, body=None):
            r = c.post(path, json=body or {})
            r.raise_for_status()
            return r.json()

        def run(wid, prompt):
            return post("/runs", dict(workspace_id=wid, message=prompt, client_request_id=key()))["run_id"]

        def wait(rid, desired):
            until = time.monotonic() + 15
            while time.monotonic() < until:
                value = c.get("/runs/" + rid).json()
                if value["state"] in desired:
                    return value
                if value["state"] in {"failed", "cancelled"}:
                    raise AssertionError(value)
                time.sleep(.04)
            raise AssertionError("local verification timed out")

        post("/session")
        status = c.get("/status").json()
        assert status["test_mode"] is True and status["available"] is True
        a = post("/workspaces", {"name": "AW03 independent approval study"})["id"]
        b = post("/workspaces", {"name": "AW03 independent concurrent study"})["id"]
        pa, pb = f"/workspaces/{a}", f"/workspaces/{b}"
        marker = "SYNTHETIC-MEMORY-004173-EUR-91.125"
        mem = post(pa + "/memory", dict(content=marker, request_id=key()))
        grant_body = dict(enabled=True, expected_revision=0, request_id=key())
        post(pa + "/connection", grant_body)
        reader = run(a, "fixture:memory")
        wait(reader, {"completed"})
        assert marker in c.get(pa + "/messages").json()["items"][-1]["content"]

        pending = run(a, "fixture:mcp-effect")
        wait(pending, {"waiting_approval"})
        t = time.monotonic()
        concurrent = run(b, "fixture:chat")
        wait(concurrent, {"completed"})
        concurrent_ms = round((time.monotonic() - t) * 1000, 2)
        assert c.get("/runs/" + pending).json()["state"] == "waiting_approval"
        assert c.get(pa + "/effects").json()["items"] == []
        approval = c.get(pa + "/approvals").json()["items"][0]
        path = "/approvals/" + approval["id"] + "/resolve"
        body = dict(decision="approve", request_id=key())
        assert c.post(path, json={**body, "approved": True}).status_code == 422
        assert c.post(path, json={**body, "note": "tampered"}).status_code == 422
        post(path, body)
        post(path, body)
        wait(pending, {"completed"})
        effects = c.get(pa + "/effects").json()["items"]
        assert len(effects) == 1 and effects[0]["status"] == "completed"
        receipt = post("/effects/" + effects[0]["id"] + "/reconcile", {"request_id": key()})
        assert receipt["status"] == "completed"

        post(pa + "/memory/" + mem["id"] + "/delete", dict(expected_version=1, request_id=key()))
        assert c.get(pa + "/memory").json()["items"] == []
        after = run(a, "fixture:memory")
        wait(after, {"completed"})
        assert marker not in c.get(pa + "/messages").json()["items"][-1]["content"]
        post(pa + "/connection", dict(enabled=False, expected_revision=1, request_id=key()))
        assert post(pa + "/connection", grant_body)["enabled"] is False

        schedule = post(pb + "/schedules", dict(message="fixture:chat", due_at=17.25, request_id=key()))
        tick = post(pb + "/clock/tick", dict(target=17.25, request_id=key()))
        wait(tick["dispatched"][0]["run_id"], {"completed"})
        repeated = post(pb + "/clock/tick", dict(target=17.25, request_id=key()))
        assert repeated["dispatched"] == []
        jobs = c.get(pb + "/schedules").json()["items"]
        assert jobs[0]["id"] == schedule["id"] and jobs[0]["state"] == "dispatched"
        assert c.post(pb + "/clock/tick", json=dict(target=16, request_id=key())).status_code == 409
        with httpx.Client(base_url=base, headers={"origin": "http://127.0.0.1:3110"}) as other:
            other.post("/session", json={}).raise_for_status()
            for path in (pa + "/memory", pa + "/connection", pa + "/approvals", pa + "/effects", pb + "/schedules"):
                assert other.get(path).status_code == 404
        print(json.dumps({"status": "PASS", "external_model_calls": 0,
                          "transport": "actual local MCP stdio fixture",
                          "cross_workspace_chat_while_approval_waits_ms_single_sample": concurrent_ms,
                          "effects": len(effects), "same_logical_approval_run": True,
                          "schedule_dispatched_once": True}, indent=2))


if __name__ == "__main__":
    main()
