import {expect, test} from "vitest";
import {boundHistory, checkText, paragraphs, pasteCells, readCells, replaceRegion, writeCells} from "./editing";
test("focused replacement uses exact offsets, preserves duplicates and unrelated Unicode", () => {
  const content = "# Museum\n\nSame text\n\nSame text\n\nGiữ 00431, 91.125 kg."; const blocks = paragraphs(content); expect(blocks).toHaveLength(4); expect(replaceRegion(content, blocks[2], "Reviewed text")).toBe("# Museum\n\nSame text\n\nReviewed text\n\nGiữ 00431, 91.125 kg."); expect(() => replaceRegion(content.replace("Museum", "Other"), blocks[2], "Changed")).toThrow(/selected text changed/);
});
test("CSV string roundtrip retains leading zeros, decimals, formula text, quotes and embedded newline", () => {
  const rows = [["ID", "Value", "Note"], ["00431", "91.125 kg", '=1+1'], ['a"b', "Việt Nam", "line one\nline two"]]; expect(readCells(writeCells(rows))).toEqual(rows);
});
test.each(['A,B\n1\n', 'A,B\n"unclosed,2', 'A,B\n"closed"extra,2', 'A,B\na"b,2', ',\n1,2', 'A\n' + "x".repeat(32001)])("malformed area fails atomically: %s", area => {expect(() => readCells(area)).toThrow();});
test("TSV and CSV paste expand shape without coercion or clipping", () => {
  const original = "ID,Value\n00431,91.125\n"; expect(readCells(pasteCells(original, '00772\t=5+5\n00891\t"line\ninside"', 1, 0, "\t"))).toEqual([["ID", "Value"], ["00772", "=5+5"], ["00891", "line\ninside"]]); expect(readCells(pasteCells(original, '"x,y",kg\n001.20,quote', 1, 1, ","))).toEqual([["ID", "Value", ""], ["00431", "x,y", "kg"], ["", "001.20", "quote"]]); expect(original).toBe("ID,Value\n00431,91.125\n");
});
test("byte, shape and history limits remain bounded", () => {
  expect(() => checkText("é".repeat(128001))).toThrow(); expect(() => pasteCells("A\n1\n", Array(2001).fill("x").join("\n"), 0, 0, "\t")).toThrow(); const history = boundHistory(Array(100).fill("x".repeat(250000))); expect(history.length).toBe(4); expect(boundHistory(Array(100).fill("small"))).toHaveLength(20);
});
