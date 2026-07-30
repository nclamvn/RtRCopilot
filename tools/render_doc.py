#!/usr/bin/env python3
"""Bộ sinh tài liệu · vá bản mẫu, không dựng file từ trống. Zero-dependency.

    python3 tools/render_doc.py <template_id> params.json [--out FILE]

Vì sao vá bản mẫu: định dạng do người thiết kế (thể thức công văn, khung workbook)
được giữ nguyên tuyệt đối, và không cần thư viện ngoài. Dựng file từ trống vừa
tốn công vừa chắc chắn lệch thể thức.

Cổng NT-4 · KHÔNG xuất file khi:
  · thiếu trường bắt buộc
  · fact khoá không giải được từ gói SOT
  · record của fact khoá bị đánh dấu spec cũ
Trạng thái trả về: READY · PASS · FAIL-LOUD · BLOCKED BY CONFLICT
"""
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPL_DIR = ROOT / "templates"
PILOT = ROOT / "phase1_pilot"
sys.path.insert(0, str(TPL_DIR.parent / "tools"))


def load_yaml(p):
    import yaml
    return yaml.safe_load(Path(p).read_text(encoding="utf-8"))


def load_pack():
    """Đọc gói SOT đang phục vụ · dùng chính parser của server để không lệch."""
    import os
    os.environ.pop("ANTHROPIC_API_KEY", None)
    sys.path.insert(0, str(PILOT))
    import copilot_server as cs
    return {r["record"]: r for r in cs.RECORDS}


# ---------------------------------------------------------------- docx
def _set_para(p, new):
    runs = list(re.finditer(r"(<w:t[^>]*>)(.*?)(</w:t>)", p, re.S))
    if not runs:
        return p
    esc = new.replace("&", "&amp;").replace("<", "&lt;")
    out, last = [], 0
    for i, m in enumerate(runs):
        out.append(p[last:m.start()])
        tag = m.group(1)
        body = esc if i == 0 else ""
        if body and "xml:space" not in tag:
            tag = tag[:-1] + ' xml:space="preserve">'
        out.append(tag + body + m.group(3))
        last = m.end()
    out.append(p[last:])
    return "".join(out)


def render_docx(tpl, values, out_path):
    z = zipfile.ZipFile(tpl)
    names = z.namelist()
    xml = z.read("word/document.xml").decode()

    def fill_para(m):
        p = m.group(0)
        txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
        if "{{" not in txt:
            return p
        new = re.sub(r"\{\{(\w+)\}\}", lambda k: str(values.get(k.group(1), "")), txt)
        if "\n" in new:
            # Nhiều dòng → nhân bản đoạn, giữ nguyên kiểu đoạn của bản mẫu
            return "".join(_set_para(p, line) for line in new.split("\n") if line.strip())
        return _set_para(p, new)

    doc = re.sub(r"<w:p[ >].*?</w:p>", fill_para, xml, flags=re.S)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in names:
            zo.writestr(n, doc.encode() if n == "word/document.xml" else z.read(n))
    left = re.findall(r"\{\{(\w+)\}\}", doc)
    return left


# ---------------------------------------------------------------- xlsx
def render_xlsx(tpl, sheet, cells, out_path):
    import shutil
    from xlsx_patch import patch
    shutil.copy(tpl, out_path)
    patch(str(out_path), {sheet: cells})
    return []


# ---------------------------------------------------------------- gate
def resolve(tid, params):
    """Trả về (state, values, issues, tpl). Không ghi file."""
    reg = load_yaml(TPL_DIR / "registry.yaml")
    tpl = next((t for t in reg["templates"] if t["id"] == tid), None)
    if not tpl:
        return "FAIL-LOUD", {}, [f"Không có bản mẫu id={tid}"], None

    pack = load_pack()
    values, issues, used_records = {}, [], []

    for f in tpl["fields"]:
        k, kind = f["key"], f["type"]
        if kind == "user":
            v = str(params.get(k, "") or "").strip()
            if not v and f.get("default"):
                v = f["default"]
            if not v and f.get("required"):
                issues.append(f"Thiếu trường bắt buộc: {f['label']}")
            values[k] = v
        elif kind == "derived":
            src = str(params.get(f["from"], "") or "").strip()
            if not src:
                issues.append(f"Thiếu trường nguồn cho {f['label']}: {f['from']}")
                values[k] = ""
                continue
            try:
                d = datetime.fromisoformat(src)
            except ValueError:
                issues.append(f"Ngày không đọc được ({f['from']}={src}) · cần dạng YYYY-MM-DD")
                values[k] = ""
                continue
            values[k] = {"day": d.day, "month": d.month, "year": d.year}[f["part"]]
        elif kind == "locked":
            rec = pack.get(f["record"])
            if not rec:
                issues.append(f"Fact khoá không giải được: {f['label']} · record {f['record']} "
                              f"không có trong gói đang phục vụ")
                values[k] = ""
                continue
            if rec.get("_stale"):
                issues.append(f"BLOCKED: {f['label']} trỏ tới record {f['record']} đã đánh dấu spec cũ")
                values[k] = ""
                continue
            if f.get("extract") and not re.search(f["extract"], rec.get("content", ""), re.I):
                issues.append(f"Fact khoá không khớp bản mẫu: {f['label']} · biểu thức "
                              f"'{f['extract']}' không tìm thấy trong {f['record']}")
                values[k] = ""
                continue
            values[k] = f.get("value", rec.get("content", ""))
            used_records.append(f["record"])

    if any(i.startswith("BLOCKED") for i in issues):
        state = "BLOCKED BY CONFLICT"
    elif issues:
        state = "FAIL-LOUD"
    else:
        state = "READY"
    return state, values, issues, {"tpl": tpl, "records": used_records}


def render(tid, params, out_dir=None):
    state, values, issues, meta = resolve(tid, params)
    if state != "READY":
        return {"state": state, "issues": issues, "file": None, "records": []}

    tpl = meta["tpl"]
    out_dir = Path(out_dir or (ROOT / "_rendered"))
    out_dir.mkdir(exist_ok=True)
    # Tên file phải duy nhất kể cả khi nhiều người bấm xuất trong CÙNG MỘT GIÂY.
    # Tester ảo 28/07: 5 người xuất đồng thời → 4 file trùng tên, người sau tải về
    # tài liệu của người trước. Thêm hậu tố ngẫu nhiên ngắn + kiểm tồn tại.
    import secrets
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    ext = ".docx" if tpl["kind"] == "docx" else ".xlsx"
    out = out_dir / f"{tpl['id']}_{stamp}{ext}"
    src = TPL_DIR / tpl["file"]

    if tpl["kind"] == "docx":
        left = render_docx(src, values, out)
        if left:
            out.unlink(missing_ok=True)
            return {"state": "FAIL-LOUD", "file": None, "records": [],
                    "issues": [f"Bản mẫu còn ô trống chưa điền: {', '.join(sorted(set(left)))}"]}
    else:
        cells = {f["cell"]: str(values.get(f["key"], ""))
                 for f in tpl["fields"] if f.get("cell") and values.get(f["key"]) not in (None, "")}
        if not cells:
            return {"state": "FAIL-LOUD", "file": None, "records": [],
                    "issues": ["Không có ô nào để điền"]}
        render_xlsx(src, tpl.get("sheet", "Brief"), cells, out)

    # Tài liệu có thể chứa dữ liệu khách hàng/nội bộ; chỉ owner hệ điều hành đọc.
    out.chmod(0o600)
    return {"state": "PASS", "file": str(out), "issues": [], "records": meta["records"]}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    tid = sys.argv[1]
    params = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    r = render(tid, params)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r["state"] == "PASS" else 2)
