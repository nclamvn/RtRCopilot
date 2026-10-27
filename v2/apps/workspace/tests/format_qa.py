"""Reproducible representative exports; invoke explicitly, not a pytest test."""
from pathlib import Path
from agent_workspace.formats import render_artifact


def main():
    root = Path(__file__).resolve().parents[1] / ".aw02-format-qa"
    root.mkdir(exist_ok=True)
    content = "# Báo cáo kiểm chứng định dạng\n\nTiếng Việt và số liệu -42, 1250, 0.015 được bảo toàn.\n\n## Nội dung dài\n\n"
    for i in range(22):
        content += f"Đoạn {i + 1}: Nguyễn và cộng đồng Đà Nẵng kiểm chứng chất lượng. " + "Nội dung dài có thể xuống dòng tự nhiên, không cắt bỏ và không thu nhỏ. " * 5 + "\n\n"
    content += "## Bảng nhiều trang\n\n| Mã | Địa điểm và nội dung | Số lượng |\n| --- | --- | --- |\n"
    for i in range(60):
        content += f"| A{i:03d} | Đà Nẵng và Hải Phòng: kiểm chứng bảng có xuống dòng tự nhiên và tiêu đề lặp lại | {-42 if i == 0 else i * 1250} |\n"
    content += "\n## Kết luận\n\nKẾT THÚC 987654.\n"
    (root / "representative.md").write_text(content)
    for fmt in ("docx", "pdf"):
        (root / f"representative.{fmt}").write_bytes(render_artifact("document", content, fmt, "Báo cáo kiểm chứng định dạng").data)
    table = "Mã,Tên,Số\n001,Đà Nẵng,-42\n002,Hải Phòng,1250\n003,Nguyễn,0.015\n"
    (root / "representative.xlsx").write_bytes(render_artifact("table", table, "xlsx").data)
    fixtures = Path(__file__).resolve().parent / "fixtures" / "formats"
    fixtures.mkdir(parents=True, exist_ok=True)
    small = "# Nhật ký cảng\n\nCảng Đà Nẵng: Nguyễn kiểm tra 1250 kiện hàng, sai lệch -42, tỷ lệ 0.015.\n\n## Kế hoạch\n\n- Giữ nguyên số liệu\n- Hoàn thành trước 17 giờ\n"
    for fmt in ("docx", "pdf"):
        (fixtures / f"harbor.{fmt}").write_bytes(render_artifact("document", small, fmt).data)
    (fixtures / "harbor.xlsx").write_bytes(render_artifact("table", table, "xlsx").data)
    print(root)


if __name__ == "__main__":
    main()
