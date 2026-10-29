"""Contractor actual HTTP acceptance, synthetic and explicit FunctionModel only.

Creates/deletes only its own isolated test workspaces; never an existing project.
No model provider, real research, connector, deployment or private-profile access.
"""
import hashlib
import io
import json
import statistics
import time
import uuid
import zipfile

import httpx
from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

BASE = "http://127.0.0.1:8130/api/workspace"
ORIGIN = "http://127.0.0.1:3130"


def main():
    start = time.perf_counter()
    checks, spaces, timings = [], [], []

    def key():
        return str(uuid.uuid4())

    with httpx.Client(base_url=BASE, headers={"origin": ORIGIN}, timeout=60) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path, data):
            response = client.post(path, json=data)
            assert response.is_success, (path, response.status_code, response.text[:300])
            return response.json()

        def proposal(wid, artifact_id, version):
            before = time.perf_counter()
            result = post("/runs", dict(workspace_id=wid, message="fixture:review", client_request_id=key(), context=dict(references=[], target=dict(kind="artifact", id=artifact_id, version=version), review_edits=True)))
            run_id = result["run_id"]
            for _ in range(300):
                state = get("/runs/" + run_id)["state"]
                if state == "completed":
                    break
                assert state not in {"failed", "cancelled"}, state
                time.sleep(.03)
            assert state == "completed"
            rows = get(f"/workspaces/{wid}/proposals")["items"]
            found = [row for row in rows if row["run_id"] == run_id]
            assert len(found) == 1
            value = get("/proposals/" + found[0]["id"])
            timings.append(round((time.perf_counter() - before) * 1000, 3))
            return value

        def handoff(wid, selections):
            response = client.post(f"/workspaces/{wid}/handoff", json=dict(selections=selections))
            assert response.is_success, (response.status_code, response.text[:300])
            assert "no-store" in response.headers["cache-control"]
            zipped = zipfile.ZipFile(io.BytesIO(response.content))
            manifest = json.loads(zipped.read("manifest.json"))
            assert manifest["format"] == "agent-workspace-handoff-v1"
            assert len(manifest["entries"]) == len(selections)
            assert set(zipped.namelist()) == {"manifest.json"} | {row["member"] for row in manifest["entries"]}
            for row in manifest["entries"]:
                raw = zipped.read(row["member"])
                assert len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["export_sha256"]
            return zipped, manifest

        post("/session", {})
        readiness = get("/readiness")
        assert readiness["available"] and readiness["test_mode"]
        try:
            wid = post("/workspaces", dict(name="AW08 contractor synthetic notebook"))["id"]
            spaces.append(wid)
            private = "UNSELECTED_PRIVATE_SYNTHETIC_" + key()
            post(f"/workspaces/{wid}/memory", dict(content=private, request_id=key()))
            source = post(f"/workspaces/{wid}/files", dict(filename="private-synthetic.txt", content=private, media_type="text/plain"))
            original = "# Thư viện mùa hè\n\nMã 000731; lượng 12.340 kg.\n\nGiữ nguyên thông tin nguồn.\n"
            doc = post(f"/workspaces/{wid}/artifacts", dict(title="Synthetic library handover", kind="document", content=original, request_id=key()))
            csv = 'Mã,Lượng,Ghi chú\n000731,12.340,"Tiếng Việt, Δ"\n000732,"1,25",=SUM(A1:A2)\n000733,-4.50,"dòng một\ndòng hai"\n'
            table = post(f"/workspaces/{wid}/artifacts", dict(title="Synthetic string ledger", kind="table", content=csv, request_id=key()))
            candidate = proposal(wid, doc["id"], 1)
            assert len(candidate["changes"]) == 2 and candidate["can_decide"]
            assert get(f"/artifacts/{doc['id']}")["content"] == original
            assert get(f"/artifacts/{doc['id']}")["version"] == 1
            foreign_change = client.post(f"/proposals/{candidate['id']}/decision", json=dict(decision="accept", change_ids=["foreign:change-1"], request_id=key()))
            assert foreign_change.status_code in {400, 409}
            accepted_key = key()
            decision = dict(decision="accept", change_ids=[candidate["changes"][0]["id"]], request_id=accepted_key)
            accepted = post(f"/proposals/{candidate['id']}/decision", decision)
            assert accepted["version"] == 2
            reviewed = get(f"/artifacts/{doc['id']}")["content"]
            assert "Proposed introduction" in reviewed and "Proposed closing" not in reviewed
            assert original in reviewed
            assert post(f"/proposals/{candidate['id']}/decision", decision) == accepted
            post(f"/artifacts/{doc['id']}/revisions", dict(expected_version=2, content=reviewed + "\nA later manual version.\n", request_id=key()))
            assert post(f"/proposals/{candidate['id']}/decision", decision) == accepted
            assert get(f"/artifacts/{doc['id']}")["version"] == 3
            changed = client.post(f"/proposals/{candidate['id']}/decision", json=dict(decision="reject", change_ids=[], request_id=accepted_key))
            assert changed.status_code == 409
            checks.append("Actual mock producer creates an unpublished two-change candidate; partial accept is one exact version, ACK replay retains that receipt even after a later manual revision")

            stale = proposal(wid, doc["id"], 3)
            current = get(f"/artifacts/{doc['id']}")["content"]
            post(f"/artifacts/{doc['id']}/revisions", dict(expected_version=3, content=current + "\nNewer independent manual work.\n", request_id=key()))
            blocked = client.post(f"/proposals/{stale['id']}/decision", json=dict(decision="accept", change_ids=[c["id"] for c in stale["changes"]], request_id=key()))
            assert blocked.status_code == 409
            rejected = post(f"/proposals/{stale['id']}/decision", dict(decision="reject", change_ids=[], request_id=key()))
            assert rejected["status"] == "rejected" and get(f"/artifacts/{doc['id']}")["version"] == 4
            with httpx.Client(base_url=BASE, headers={"origin": ORIGIN}, timeout=15) as other:
                other.post("/session", json={}).raise_for_status()
                assert other.get(f"/proposals/{candidate['id']}").status_code == 404
                assert other.post(f"/workspaces/{wid}/handoff", json={"selections": [{"artifact_id": doc["id"], "version": 1, "format": "md"}]}).status_code == 404
            checks.append("A newer manual version blocks stale acceptance but still permits nonpublishing rejection; foreign session cannot inspect candidate or handoff")

            pending = proposal(wid, doc["id"], 4)
            selections = [dict(artifact_id=doc["id"], version=1, format="md"), dict(artifact_id=table["id"], version=1, format="xlsx")]
            zipped, manifest = handoff(wid, selections)
            doc_member = next(row for row in manifest["entries"] if row["artifact_id"] == doc["id"])
            table_member = next(row for row in manifest["entries"] if row["artifact_id"] == table["id"])
            assert zipped.read(doc_member["member"]).decode() == original
            sheet = load_workbook(io.BytesIO(zipped.read(table_member["member"])), data_only=False).active
            assert [sheet.cell(2, i).value for i in range(1, 4)] == ["000731", "12.340", "Tiếng Việt, Δ"]
            assert sheet.cell(3, 3).value == "=SUM(A1:A2)" and sheet.cell(3, 3).data_type == "s"
            assert sheet.cell(4, 3).value == "dòng một\ndòng hai"
            for name in zipped.namelist():
                assert private.encode() not in zipped.read(name)
                assert pending["id"].encode() not in zipped.read(name)
            assert source["id"] not in json.dumps(manifest)
            zipped, manifest = handoff(wid, [dict(artifact_id=doc["id"], version=1, format="docx")])
            text = "\n".join(p.text for p in Document(io.BytesIO(zipped.read(manifest["entries"][0]["member"]))).paragraphs)
            assert "Thư viện mùa hè" in text and "000731" in text and "12.340 kg" in text
            zipped, manifest = handoff(wid, [dict(artifact_id=doc["id"], version=1, format="pdf")])
            text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(zipped.read(manifest["entries"][0]["member"]))).pages)
            assert "Thư viện mùa hè" in text and "000731" in text and "12.340 kg" in text
            missing = client.post(f"/workspaces/{wid}/handoff", json=dict(selections=[selections[0], dict(artifact_id="missing-synthetic-id", version=1, format="md")]))
            assert missing.status_code == 404 and "application/zip" not in missing.headers.get("content-type", "")
            checks.append("Selected old saved version and literal-string XLSX values parsed back, including Unicode/leading zero/decimal/formula-like text/newline; DOCX/PDF parsed back; no private memory, unselected source or pending candidate in the handoff")
            result = dict(status="PASS", date="2026-10-29", provenance="Contractor actual HTTP/SQLite/DBOS and existing binary renderers, explicit scripted FunctionModel, synthetic data only", checks=checks, measurements=dict(mock_review_runs=len(timings), request_to_readable_candidate_ms=timings, request_to_readable_candidate_ms_median=round(statistics.median(timings), 3), natural_language_quality="NOT_MEASURED", real_first_useful_ai_output_ms=None), external_calls=0, elapsed_seconds=round(time.perf_counter() - start, 3), limitations=["Scripted candidate is prewritten transport behavior, not AI semantic review or human acceptance", "Small warm samples with concurrent local testing are not capacity/provider-latency certification"])
        finally:
            for wid in spaces:
                preview = get(f"/workspaces/{wid}/delete-preview")
                assert preview["blocked_reason"] is None
                post(f"/workspaces/{wid}/delete", dict(confirmation_token=preview["confirmation_token"], confirm_name=preview["name"], request_id=key()))
        result["own_workspaces_created_and_deleted"] = len(spaces)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
