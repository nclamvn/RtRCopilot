# Portable export fonts

Noto Sans Regular and Bold are unmodified files from the Codex runtime's
LibreOffice font bundle (26.1026.10807). They are packaged with this application
so PDF generation never looks up host fonts or downloads a font. Upstream:
https://github.com/notofonts/latin-greek-cyrillic . Font license and copyright
are reproduced in LICENSE-NOTO.txt. Font coverage is checked before PDF export;
unsupported glyphs cause an explicit error rather than missing-glyph boxes.
