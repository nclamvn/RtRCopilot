# RtR Enterprise Intelligence Atlas

Bộ hồ sơ chiến lược 16 trang mô tả RtR Copilot như lớp Enterprise Intelligence & Action OS trên hệ sinh thái RtR.

## Nội dung

- `RtR_Enterprise_Intelligence_Atlas.pdf`: bản phát hành đã kiểm tra bố cục.
- `build_atlas.py`: nguồn dựng ReportLab.
- `DESIGN_PHILOSOPHY.md`: nguyên tắc thị giác Monochrome Intelligence.

## Dựng lại

Yêu cầu Python, ReportLab và ba font Inter: `Inter-Regular.ttf`, `Inter-SemiBold.ttf`, `Inter-Bold.ttf`.

```bash
RTR_ATLAS_FONT_DIR=/path/to/inter-fonts \
python docs/enterprise-intelligence-atlas/build_atlas.py
```

Có thể đặt đường dẫn xuất khác qua biến `RTR_ATLAS_OUTPUT`.
