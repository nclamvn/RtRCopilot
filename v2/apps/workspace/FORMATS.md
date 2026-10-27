# Workspace format contract

This is a deterministic, local format capability, not evidence of model quality.
Original uploaded bytes are retained by the store. Extraction is an explicitly
labelled text projection, not an Office/PDF round-trip or full-fidelity preview.

## Interface

`extract_upload(filename, data)` returns `Extraction(text, media_type, metadata,
warnings)`. `validate_artifact(kind, content)` checks canonical content.
`render_artifact(kind, content, format, title="Document")` returns
`Export(data, media_type, extension, warnings)`. Failures raise `FormatError`
with a stable `.code`; no successful export replaces the canonical draft.

Canonical `document` content is Markdown. Canonical `table` content is rectangular
CSV with a non-empty header. Document downloads support MD/DOCX/PDF; tables
support CSV/XLSX. MD download preserves every canonical byte encoded as UTF-8.

## Supported input and honest limits

- UTF-8 TXT/MD/CSV; malformed/ragged CSV is rejected rather than repaired.
- DOCX: paragraph text, heading/list markers, rectangular tables, labelled
  header/footer text, stored field display text and hyperlink labels/targets.
  No fields are refreshed and no links are followed. Images are flagged as
  omitted non-text content; original remains available. Tracked changes,
  equations, footnotes/endnotes, text boxes, content controls, merged/nested
  tables and embedded active objects are not accepted.
- XLSX: sheet-labelled data, comments and hyperlink targets as labelled notes.
  Original types/styles are not reproduced by extraction. Formulas are explicitly
  unsupported, including formulas without cached values; never silently `None`.
  Merged cells/charts/images are not accepted. No formulas or links are evaluated.
- Text PDF: text layers with explicit layout/reading-order review warning.
  Encrypted, image/scanned, annotated or empty text-layer pages are rejected.
  There is no OCR and no claim to reconstruct PDF tables or page layout.

Uploads: 256000 bytes each. Extracted/canonical text: 1 MB. Office ZIP: 256
members, 20 MB expanded, per-member compression ratio <=200 beyond 100 KB.
Tables: <=2000 rows, <=40 columns, <=20000 cells and <=32000 characters/cell.
PDF: <=100 pages and <=2 MB expanded content stream per page. Binary extraction
and rendering have disposable spawned processes: 15 s wall deadline, 10 s CPU,
512 MB RSS checked every 25 ms (not a kernel sandbox; a fast transient allocation
may precede the check), plus Linux address-space limit. At most two workers run
per API process; excess requests return `format_busy` after a 0.5 s queue wait.
Output is limited to 5 MB.
Macros, unsafe/duplicate ZIP members, XML entities and non-hyperlink external
resources fail closed. The libraries do not extract ZIP members to host paths.
Worker sockets deny network connections; no shell or arbitrary code tool exists.

## Export fidelity and safety

DOCX/PDF export supports plain prose, semantic headings, flat list markers and
rectangular pipe tables (at most 8 columns). Unsupported Markdown such as code,
images, HTML, inline formatting and links causes an explicit export failure;
the Markdown draft/download remains intact. A4, legible 11 pt body text,
monochrome styling, wrapped/repeated table headers and flowing pages are used.
No content slicing, legacy renderer, watermark or dynamic font download is used.
PDF embeds packaged SIL-OFL Noto Sans; glyph coverage is checked and unsupported
glyphs fail explicitly. DOCX requests Noto Sans and remains editable; the consuming
Word processor controls font substitution if Noto Sans is not installed there.

CSV export may normalize quoting/newlines. Formula-like text (`=`, `+`, `-`, `@`,
also after whitespace) is prefixed by an apostrophe **only in the safe export**,
with an explicit warning. Canonical content is unchanged; original-source download
is byte-exact. Numeric text such as `-42` or `-0.015` is not escaped or rewritten.
XLSX stores formula-like cells as literal strings (`data_type=s`), never formulas,
and warns. Only lossless <=15-digit integers are numeric cells (`-42` stays a
number); exact decimal strings, long integers and leading-zero IDs remain text.
No locale conversion or IEEE-754 rounding of those strings is performed.

## Reproduce structural and visual QA

Run `PYTHONPATH=src .venv/bin/python -m pytest tests/test_formats.py -q`.
Run `PYTHONPATH=src .venv/bin/python tests/format_qa.py` for a synthetic Vietnamese
multi-page paragraph/table fixture with all row IDs and final marker. Outputs
are in ignored `.aw02-format-qa/`, not a project copy or installed temp environment.
Small checked-in binary fixtures support browser integration tests.

DOCX was rendered with the bundled `render_docx.py` and bundled LibreOffice
resolved by the workspace dependency loader. All representative page PNGs were
visually inspected for Vietnamese glyphs, wrapping, repeated headers and clipping.
The renderer is QA-only; the product uses its own pinned Python 3.12 environment.
This is assistant-authored synthetic structural/visual evidence, not independent
human acceptance, semantic evaluation or a benchmark against a direct agent.
