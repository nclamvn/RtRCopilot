#!/usr/bin/env python3
"""Trích text từ nguồn (docx/xlsx/md/txt) để SOẠN candidate với evidence_span verbatim.

READ-ONLY tuyệt đối — chỉ đọc nguồn, in ra stdout kèm NEO VỊ TRÍ (sheet!ô cho xlsx,
số ¶ cho docx, số dòng cho md/txt). Không sửa nguồn, không ghi file.

Đây là đòn bẩy curator-sustainability: biến "đọc file bằng mắt rồi gõ tay" thành lặp-lại-được.
Pattern tái dùng: docx = zipfile+re (như tools/make_templates.py), xlsx = openpyxl data_only
(như kernel/registry/atomize.py — inline-string BẮT BUỘC data_only mới ra value).

Dùng:
  python3 tools/extract_source.py <path>
  python3 tools/extract_source.py <path.xlsx> --sheet "KEY FEATURES"
  python3 tools/extract_source.py <path> --grep OmniSight
"""
import sys
import os
import re
import html
import argparse
import zipfile


def extract_xlsx(path, only_sheet=None):
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    wb = load_workbook(path, data_only=True)   # data_only: lấy value, giải inline-string
    for name in wb.sheetnames:
        if only_sheet and name != only_sheet:
            continue
        ws = wb[name]
        rows_out = []
        for row in ws.iter_rows():
            cells = [(f"{get_column_letter(c.column)}{c.row}", str(c.value).strip())
                     for c in row if c.value is not None and str(c.value).strip()]
            if cells:
                rows_out.append(cells)
        if not rows_out:
            continue
        yield f"\n===== SHEET: {name} ({len(rows_out)} hàng có dữ liệu) ====="
        for cells in rows_out:
            yield "  " + "  |  ".join(f"[{ref}] {val}" for ref, val in cells)


def _docx_paras(path):
    z = zipfile.ZipFile(path)
    parts = ["word/document.xml"]
    # gồm cả header/footer nếu có (đôi khi tên sản phẩm nằm ở header)
    parts += [n for n in z.namelist() if re.match(r"word/(header|footer)\d*\.xml$", n)]
    for part in parts:
        try:
            xml = z.read(part).decode("utf-8", "replace")
        except KeyError:
            continue
        # mỗi <w:p> là một paragraph (kể cả ô bảng); gộp mọi <w:t> bên trong
        for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.S):
            txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
            txt = html.unescape(txt).strip()
            if txt:
                yield part, txt


def extract_docx(path, only_sheet=None):
    n = 0
    for part, txt in _docx_paras(path):
        n += 1
        tag = "" if part == "word/document.xml" else f" ({part.split('/')[-1]})"
        yield f"  ¶{n}{tag}: {txt}"
    if n == 0:
        yield "  (không trích được paragraph — file có thể rỗng hoặc định dạng lạ)"


def extract_text(path, only_sheet=None):
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if line.strip():
                yield f"  {i:4}: {line}"


def main():
    ap = argparse.ArgumentParser(description="Trích text nguồn để soạn candidate (READ-ONLY).")
    ap.add_argument("path")
    ap.add_argument("--sheet", default=None, help="xlsx: chỉ 1 sheet")
    ap.add_argument("--grep", default=None, help="chỉ in dòng khớp (không phân biệt hoa/thường)")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        sys.exit(f"không thấy file: {args.path}")
    ext = os.path.splitext(args.path)[1].lower()
    dispatch = {".xlsx": extract_xlsx, ".docx": extract_docx,
                ".md": extract_text, ".txt": extract_text, ".yaml": extract_text}
    fn = dispatch.get(ext)
    if fn is None:
        sys.exit(f"chưa hỗ trợ đuôi {ext} (dùng docx/xlsx/md/txt/yaml; .pdf cần lib riêng)")

    print(f"# NGUỒN: {args.path}")
    print(f"# (READ-ONLY · neo vị trí để trích evidence_span verbatim)")
    pat = re.compile(re.escape(args.grep), re.I) if args.grep else None
    for line in fn(args.path, only_sheet=args.sheet):
        if pat and not pat.search(line):
            continue
        print(line)


if __name__ == "__main__":
    main()
