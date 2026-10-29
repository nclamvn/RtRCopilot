/** Deterministic draft adapters. Text stays Markdown / rectangular string CSV. */
export const EDIT_BYTES = 256_000;
export function checkText(content: string) {
  if (new TextEncoder().encode(content).length > EDIT_BYTES || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(content)) throw new Error("Keep this draft within 256,000 UTF-8 bytes and remove control characters. Nothing was applied.");
}
export type Region = {start: number; end: number; source: string};
export type EditBuffers = {focus?: {region: Region; replacement: string}; paste?: string};
export function paragraphs(content: string): Region[] {
  const result: Region[] = []; const pattern = /\S[\s\S]*?(?=\r?\n[ \t]*\r?\n|$)/g;
  for (const match of content.matchAll(pattern)) {result.push({start: match.index!, end: match.index! + match[0].length, source: match[0]}); if (result.length >= 1000) break;}
  return result;
}
export function replaceRegion(content: string, region: Region, replacement: string): string {
  if (!Number.isSafeInteger(region.start) || !Number.isSafeInteger(region.end) || region.start < 0 || region.end <= region.start || region.end > content.length || content.slice(region.start, region.end) !== region.source) throw new Error("The selected text changed. Select it again; unrelated text was not changed.");
  const result = content.slice(0, region.start) + replacement + content.slice(region.end); checkText(result); return result;
}
/** Strict quoted CSV/TSV parser: never infer numbers, trim, evaluate or repair. */
export function readCells(content: string, delimiter: "," | "\t" = ",", requireHeader = true): string[][] {
  checkText(content); const rows: string[][] = []; let row: string[] = [], field = "", quoted = false, closed = false;
  const finishCell = () => {if (field.length > 32000) throw new Error("A cell exceeds 32,000 characters. Nothing was applied."); row.push(field); field = ""; closed = false;};
  const finishRow = () => {finishCell(); rows.push(row); row = [];};
  for (let index = 0; index < content.length; index++) {
    const character = content[index];
    if (quoted) {if (character === '"') {if (content[index + 1] === '"') {field += '"'; index++;} else {quoted = false; closed = true;}} else field += character; continue;}
    if (character === delimiter) {finishCell(); continue;}
    if (character === "\n" || character === "\r") {if (character === "\r" && content[index + 1] === "\n") index++; finishRow(); continue;}
    if (closed) throw new Error("Text follows a closing quote. Paste a rectangular CSV or TSV area. Nothing was applied.");
    if (character === '"') {if (field) throw new Error("A quote inside a cell must be escaped. Nothing was applied."); quoted = true;} else field += character;
  }
  if (quoted) throw new Error("The pasted area has an unclosed quote. Nothing was applied.");
  if (field || row.length || closed) finishRow();
  const width = rows[0]?.length ?? 0;
  if (!width || requireHeader && !rows[0].some(value => value.length)) throw new Error("A table needs a non-empty header row. Nothing was applied.");
  if (rows.length > 2000 || width > 40 || rows.length * width > 20_000 || rows.some(value => value.length !== width)) throw new Error("Use a rectangular area within 2,000 rows, 40 columns and 20,000 cells. No cells were clipped or repaired.");
  return rows;
}
export function writeCells(rows: string[][]): string {
  const text = rows.map(row => row.map(value => /[",\r\n]/.test(value) ? '"' + value.replaceAll('"', '""') + '"' : value).join(",")).join("\n") + "\n";
  readCells(text); return text;
}
export function pasteCells(content: string, paste: string, row: number, column: number, delimiter: "," | "\t"): string {
  const current = readCells(content), area = readCells(paste, delimiter, false);
  if (!Number.isSafeInteger(row) || !Number.isSafeInteger(column) || row < 0 || column < 0 || row >= current.length || column >= current[0].length) throw new Error("Select an existing starting cell. Nothing was applied.");
  const height = Math.max(current.length, row + area.length), width = Math.max(current[0].length, column + area[0].length);
  if (height > 2000 || width > 40 || height * width > 20_000) throw new Error("The paste exceeds the table limits. Nothing was applied.");
  const next = Array.from({length: height}, (_, y) => Array.from({length: width}, (_, x) => current[y]?.[x] ?? ""));
  area.forEach((values, y) => values.forEach((value, x) => {next[row + y][column + x] = value;})); return writeCells(next);
}
export function boundHistory(values: string[]): string[] {
  let bytes = 0; const kept: string[] = [];
  for (let index = values.length - 1; index >= 0 && kept.length < 20; index--) {bytes += new TextEncoder().encode(values[index]).length; if (bytes > 1_000_000) break; kept.unshift(values[index]);}
  return kept;
}
