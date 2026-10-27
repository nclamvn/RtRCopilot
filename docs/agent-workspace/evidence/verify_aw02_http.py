"""Reproducible local-only manual-authoring smoke; no model or chat dispatch.

Run with the workspace Python environment and a simulation API on loopback8110.
Creates one small synthetic workspace. Never changes or deletes existing data.
"""
import io
import json
import time
import uuid

import httpx
from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader


def main():
    base = "http://127.0.0.1:8110/api/workspace"
    measurements = {}
    with httpx.Client(base_url=base, headers={"origin": "http://127.0.0.1:3110"}, timeout=25) as c:
        def post(path, body=None):
            r = c.post(path, json=body or {})
            r.raise_for_status()
            return r.json()

        post("/session")
        assert c.get("/status").json()["test_mode"] is True
        w = post("/workspaces", {"name": "AW02 independent local verification"})["id"]
        prefix = f"/workspaces/{w}"
        source = "Vietnamese: Đà Nẵng\nBudget 24,750\nEnd marker 987654\n"
        batch = post(prefix + "/files/batch", {"files": [
            {"filename": "source.md", "content": source},
            {"filename": "../bad.txt", "content": "must not be saved"},
        ]})
        assert len(batch["accepted"]) == len(batch["errors"]) == 1
        fid = batch["accepted"][0]["id"]
        assert c.get(f"/files/{fid}/download").content == source.encode()
        content = "# Working note\n\nĐà Nẵng: budget 24,750.\n\nNext review: 18 November.\n\nInvent. Build. Prove.\n\n| Key | Value |\n| --- | --- |\n| - | -- |\n| Reserve | 0.015 |\n"
        body = {"title": "Working note", "kind": "document", "content": content, "request_id": str(uuid.uuid4())}
        t = time.perf_counter()
        item = post(prefix + "/artifacts", body)
        measurements["manual_create_ms"] = round((time.perf_counter() - t) * 1000, 2)
        aid = item["id"]
        assert post(prefix + "/artifacts", body)["id"] == aid
        edited = content.replace("18 November", "20 November")
        post(f"/artifacts/{aid}/revisions", {"expected_version": 1, "content": edited, "request_id": str(uuid.uuid4())})
        assert c.get(f"/artifacts/{aid}?version=1").json()["content"] == content
        assert c.get(f"/artifacts/{aid}").json()["content"] == edited
        for fmt in ("md", "docx", "pdf"):
            t = time.perf_counter()
            r = c.get(f"/artifacts/{aid}/download?version=2&format={fmt}")
            r.raise_for_status()
            measurements[fmt + "_export_ms"] = round((time.perf_counter() - t) * 1000, 2)
            if fmt == "md":
                assert r.text == edited
            elif fmt == "docx":
                d = Document(io.BytesIO(r.content))
                assert "20 November" in "\n".join(p.text for p in d.paragraphs)
                assert [x.text for x in d.tables[0].rows[1].cells] == ["-", "--"]
            else:
                text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
                assert all(x in text for x in ("Đà Nẵng", "24,750", "20 November", "Invent. Build. Prove.", "0.015"))
        table = "Name,Value\nĐà Nẵng,-42\nReserve,0.015\nID,0012\nLiteral,=1+1\n"
        tid = post(prefix + "/artifacts", {"title": "Data", "kind": "table", "content": table, "request_id": str(uuid.uuid4())})["id"]
        xlsx = c.get(f"/artifacts/{tid}/download?format=xlsx")
        xlsx.raise_for_status()
        wb = load_workbook(io.BytesIO(xlsx.content), data_only=False)
        cells = list(wb.active.values)
        assert cells[1] == ("Đà Nẵng", -42) and cells[2][1] == "0.015" and cells[3][1] == "0012"
        assert wb.active["B5"].data_type == "s" and wb.active["B5"].value == "=1+1"
        safe_csv = c.get(f"/artifacts/{tid}/download?format=csv")
        assert "formula" in safe_csv.headers["X-Workspace-Export-Warnings"].lower()
        assert c.get(f"/artifacts/{tid}").json()["content"] == table
        research = post(prefix + "/research/search", {"query": "Harbor"})
        assert research["fixture"] is True and len(research["results"]) == 2
        assert c.post(prefix + "/research/read", json={"source_id": "http://169.254.169.254/"}).status_code == 404
        assert c.get(prefix + "/messages").json()["items"] == []
        with httpx.Client(base_url=base, headers={"origin": "http://127.0.0.1:3110"}) as other:
            other.post("/session", json={}).raise_for_status()
            assert other.get(f"/artifacts/{aid}").status_code == 404
            assert other.get(f"/files/{fid}/download").status_code == 404
        print(json.dumps({"status": "PASS", "model_dispatches": 0, "external_calls": 0, "timings_single_local_sample": measurements}, indent=2))


if __name__ == "__main__":
    main()
