#!/usr/bin/env python3
"""Rút bản mẫu docx từ một công văn thật · giữ nguyên định dạng, chỉ thay nội dung bằng ô trống.

Chạy một lần (hoặc chạy lại khi muốn đổi bản gốc):

    python3 tools/make_templates.py

Vì sao rút từ file thật thay vì dựng mới: định dạng công văn nhà nước (thể thức
Nghị định 30/2020) do người soạn kỹ — canh lề, cỡ chữ, khoảng cách quốc hiệu.
Dựng lại từ trống chắc chắn lệch. Rút mẫu giữ được toàn bộ và không cần thư viện.
"""
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "templates"
OUT.mkdir(exist_ok=True)

SRC = None
for base in (Path("/Users/os/RtR/KnowledgeBase"),
             Path("/sessions/intelligent-affectionate-planck/mnt/KnowledgeBase")):
    p = base / "HoSo_CNCL_2_Cay_Che_SauRieng/00_GUI_DI/A_Gui_Vinatea/00_CongVan_1906_2026_CV_RTR.docx"
    if p.exists():
        SRC = p
        break
if SRC is None:
    raise SystemExit("Không tìm thấy công văn gốc để rút mẫu")


def para_text(p):
    return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))


def set_para_text(p, new):
    """Đặt toàn bộ chữ của đoạn vào run ĐẦU, làm rỗng các run sau.
    Word hay chẻ một câu thành nhiều run; gộp lại rồi đặt vào run đầu là cách
    giữ được kiểu chữ của đoạn mà không phải dựng lại cây XML."""
    runs = list(re.finditer(r"(<w:t[^>]*>)(.*?)(</w:t>)", p, re.S))
    if not runs:
        return p
    out, last = [], 0
    for i, m in enumerate(runs):
        out.append(p[last:m.start()])
        body = new if i == 0 else ""
        tag = m.group(1)
        if body and 'xml:space' not in tag:
            tag = tag[:-1] + ' xml:space="preserve">'
        out.append(tag + body.replace("&", "&amp;").replace("<", "&lt;") + m.group(3))
        last = m.end()
    out.append(p[last:])
    return "".join(out)


def build_congvan():
    z = zipfile.ZipFile(SRC)
    names = z.namelist()
    xml = z.read("word/document.xml").decode()
    paras = list(re.finditer(r"<w:p[ >].*?</w:p>", xml, re.S))

    # Ánh xạ đoạn → ô trống. Chỉ số lấy từ bản gốc, in ra để đối chiếu khi bản gốc đổi.
    REPLACE = {
        1:  "{{ten_phap_nhan}}",
        3:  "Số: {{so_cong_van}}",
        4:  "V/v {{trich_yeu}}",
        5:  "",
        9:  "{{dia_danh}}, ngày {{ngay}} tháng {{thang}} năm {{nam}}",
        10: "Kính gửi: {{noi_nhan}}",
        11: "{{noi_nhan_phu}}",
    }
    # Nơi nhận + người ký (đếm ngược từ cuối để không phụ thuộc độ dài phần thân)
    n = len(paras)
    REPLACE[n - 6] = "{{noi_nhan_list}}"   # danh sách nơi nhận
    REPLACE[n - 5] = ""                    # dòng nơi nhận cũ thứ hai
    REPLACE[n - 4] = "- Lưu: VT."
    REPLACE[n - 1] = "{{nguoi_ky}}"

    # Toàn bộ phần căn cứ + nội dung (đoạn 12 trở đi, trừ phần ký cuối) → hai ô trống
    body_start, body_end = 12, len(paras) - 6
    new_xml, cursor = [], 0
    for i, m in enumerate(paras):
        new_xml.append(xml[cursor:m.start()])
        p = m.group(0)
        if i in REPLACE:
            p = set_para_text(p, REPLACE[i])
        elif i == body_start:
            p = set_para_text(p, "{{can_cu}}")
        elif i == body_start + 1:
            p = set_para_text(p, "{{noi_dung}}")
        elif body_start + 1 < i < body_end:
            p = ""   # bỏ các đoạn nội dung cũ
        new_xml.append(p)
        cursor = m.end()
    new_xml.append(xml[cursor:])
    doc = "".join(new_xml)

    out = OUT / "CongVan_RTR.docx"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in names:
            zo.writestr(n, doc.encode() if n == "word/document.xml" else z.read(n))
    toks = sorted(set(re.findall(r"\{\{(\w+)\}\}", doc)))
    print(f"CongVan_RTR.docx · ô trống: {', '.join(toks)}")
    return toks


def copy_salesbrief():
    for base in (Path("/Users/os/RtR/KnowledgeBase"),
                 Path("/sessions/intelligent-affectionate-planck/mnt/KnowledgeBase")):
        p = base / "Sales_Brief_System/RtR_Sales_Brief_Template_VN.xlsx"
        if p.exists():
            shutil.copy(p, OUT / "SalesBrief_VN.xlsx")
            print("SalesBrief_VN.xlsx · chép nguyên bản workbook (đã có bản đồ ô sẵn)")
            return
    print("CẢNH BÁO: không thấy workbook Sales Brief")


def build_from_congvan(out_name, replace_map, body_slots):
    """Dựng bản mẫu mới bằng cách mượn khung định dạng của công văn gốc.

    Vì sao mượn: file gốc đã có font tiếng Việt, cỡ chữ, lề, và các kiểu đoạn
    hợp lệ. Dựng docx từ trống thì phải tự viết styles.xml, dễ lệch font
    tiếng Việt và tốn công gấp nhiều lần cho cùng một kết quả.
    """
    z = zipfile.ZipFile(SRC)
    names = z.namelist()
    xml = z.read("word/document.xml").decode()
    paras = list(re.finditer(r"<w:p[ >].*?</w:p>", xml, re.S))
    n = len(paras)
    new_xml, cursor, slot = [], 0, 0
    for i, m in enumerate(paras):
        new_xml.append(xml[cursor:m.start()])
        p = m.group(0)
        if i in replace_map:
            p = set_para_text(p, replace_map[i])
        elif 12 <= i < n - 6:
            p = set_para_text(p, body_slots[slot]) if slot < len(body_slots) else ""
            slot += 1
        elif i >= n - 6:
            p = ""      # bỏ khối nơi nhận + chữ ký của công văn
        new_xml.append(p)
        cursor = m.end()
    new_xml.append(xml[cursor:])
    doc = "".join(new_xml)
    out = OUT / out_name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for nm in names:
            zo.writestr(nm, doc.encode() if nm == "word/document.xml" else z.read(nm))
    toks = sorted(set(re.findall(r"\{\{(\w+)\}\}", doc)))
    print(f"{out_name} · ô trống: {', '.join(toks)}")


def build_factsheet():
    build_from_congvan("FactSheet_SanPham.docx",
        {0: "", 1: "{{ten_phap_nhan}}", 2: "", 3: "", 4: "", 5: "",
         6: "FACT-SHEET SẢN PHẨM", 7: "{{ten_san_pham}}", 8: "",
         9: "Cập nhật {{ngay}}/{{thang}}/{{nam}} · nguồn: SOT nội bộ",
         10: "{{mo_ta_ngan}}", 11: ""},
        ["THÔNG SỐ CHÍNH",
         "Tải trọng: {{payload}}",
         "Tầm điều khiển: {{tam_dieu_khien}}",
         "Thời gian bay: {{thoi_gian_bay}}",
         "Kháng bụi nước: {{ip_rating}}",
         "GHI CHÚ",
         "{{ghi_chu}}",
         "Mọi số liệu trong tài liệu này lấy từ nguồn sự thật nội bộ và không sửa tay được. "
         "Số nào cần cập nhật thì sửa ở nguồn rồi tạo lại tài liệu."])


def build_slidecard():
    build_from_congvan("SlideCard_RtR.docx",
        {0: "", 1: "{{ten_phap_nhan}}", 2: "", 3: "", 4: "", 5: "",
         6: "SLIDE CARD", 7: "{{tieu_de_slide}}", 8: "",
         9: "Deck: {{ten_deck}} · slide {{so_slide}}", 10: "", 11: ""},
        ["THÔNG ĐIỆP MỘT CÂU",
         "{{thong_diep}}",
         "BA Ý CHÍNH",
         "{{y_chinh}}",
         "SỐ LIỆU DẪN CHỨNG",
         "Tải trọng {{payload}} · tầm {{tam_dieu_khien}} · thời gian bay {{thoi_gian_bay}}",
         "NGUỒN",
         "Số liệu lấy từ nguồn sự thật nội bộ · mã record ghi trong phần ghi chú slide.",
         "GHI CHÚ NGƯỜI TRÌNH BÀY",
         "{{ghi_chu_trinh_bay}}"])


if __name__ == "__main__":
    build_congvan()
    build_factsheet()
    build_slidecard()
    copy_salesbrief()
