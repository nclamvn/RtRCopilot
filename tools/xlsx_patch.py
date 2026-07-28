"""Vá ô xlsx bằng XML trực tiếp · giữ nguyên mọi thứ khác (kể cả giá trị công thức đã tính)."""
import re, shutil, zipfile, tempfile, os
from pathlib import Path
from xml.sax.saxutils import escape

def col_idx(ref):
    m = re.match(r"([A-Z]+)(\d+)", ref); c = 0
    for ch in m.group(1): c = c * 26 + ord(ch) - 64
    return c, int(m.group(2))

def patch(xlsx, edits):
    """edits: {sheet_name: {cell_ref: new_text}}"""
    tmp = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(xlsx) as z:
        names = z.namelist(); z.extractall(tmp)
    wbx = (tmp / "xl/workbook.xml").read_text(encoding="utf-8")
    rels = (tmp / "xl/_rels/workbook.xml.rels").read_text(encoding="utf-8")
    rid2t = {}
    for tag in re.findall(r'<Relationship [^>]*/>', rels):
        i = re.search(r'Id="([^"]+)"', tag); t = re.search(r'Target="([^"]+)"', tag)
        if i and t: rid2t[i.group(1)] = t.group(1)
    name2file = {}
    for nm, rid in re.findall(r'<(?:x:)?sheet name="([^"]+)"[^>]*r:id="([^"]+)"', wbx):
        t = rid2t[rid]
        t = t.lstrip("/")
        name2file[nm] = t if t.startswith("xl/") else "xl/" + t
    changed = 0
    for sheet, cells in edits.items():
        p = tmp / name2file[sheet]
        xml = p.read_text(encoding="utf-8")
        px = "x:" if "<x:sheetData" in xml else ""
        for ref, val in cells.items():
            new_c = (f'<{px}c r="{ref}" t="inlineStr"><{px}is><{px}t xml:space="preserve">'
                     f'{escape(val)}</{px}t></{px}is></{px}c>')
            pat = re.compile(r'<%sc r="%s"(?:[^>]*?/>|[^>]*?>.*?</%sc>)' % (px, ref, px), re.S)
            if pat.search(xml):
                # giữ style cũ nếu có
                old = pat.search(xml).group(0)
                sm = re.search(r'\ss="(\d+)"', old)
                if sm: new_c = new_c.replace(f'r="{ref}"', f'r="{ref}" s="{sm.group(1)}"')
                xml = pat.sub(new_c, xml, count=1)
            else:
                ci, ri = col_idx(ref)
                rpat = re.compile(r'(<%srow r="%d"(?: [^>]*)?>)(.*?)(</%srow>)' % (px, ri, px), re.S)
                m = rpat.search(xml)
                if not m:
                    raise SystemExit(f"{xlsx}:{sheet} không có row {ri}")
                body = m.group(2)
                cs = list(re.finditer(r'<%sc r="([A-Z]+\d+)"(?:[^>]*?/>|[^>]*?>.*?</%sc>)' % (px, px), body, re.S))
                pos = len(body)
                for c in cs:
                    if col_idx(c.group(1))[0] > ci: pos = c.start(); break
                body = body[:pos] + new_c + body[pos:]
                xml = xml[:m.start()] + m.group(1) + body + m.group(3) + xml[m.end():]
            changed += 1
        p.write_text(xml, encoding="utf-8")
    out = xlsx + ".new"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names: z.write(tmp / n, n)
    shutil.move(out, xlsx); shutil.rmtree(tmp)
    return changed
