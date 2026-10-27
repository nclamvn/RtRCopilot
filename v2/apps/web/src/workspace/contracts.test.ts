import {describe, expect, test} from "vitest";
import {applyEvent, safeLink, terminal, uploadError, type WorkspaceEvent} from "./contracts";

describe("Workspace live protocol", () => {
  const initial = {cursor: 0, content: "", state: "queued", activities: []};
  const event = (seq: number, type: string, data: Record<string, unknown>): WorkspaceEvent => ({seq, type, data, run_id: "run-a"});
  test("appends provisional deltas and replaces with authoritative final snapshot", () => {
    const first = applyEvent(initial, event(1, "message.delta", {text: "Hello "}));
    const second = applyEvent(first, event(2, "message.delta", {text: "there"}));
    expect(second.content).toBe("Hello there");
    expect(applyEvent(second, event(3, "message.final", {content: "Hello there."})).content).toBe("Hello there.");
  });
  test("ignores duplicate/out-of-order sequence instead of duplicating content", () => {
    const state = applyEvent(initial, event(5, "message.delta", {text: "Once"}));
    expect(applyEvent(state, event(5, "message.delta", {text: "Once"}))).toBe(state);
    expect(applyEvent(state, event(3, "message.delta", {text: "Older"}))).toBe(state);
  });
  test("shows tool activity, no private reasoning, and explicit terminal states", () => {
    const state = applyEvent(initial, event(1, "tool.start", {name: "read_file", private_reasoning: "hidden"}));
    expect(state.activities).toEqual(["Working: read_file"]);
    expect(terminal("cancel_requested")).toBe(false);
    expect(terminal("cancelled")).toBe(true);
    expect(terminal("interrupted")).toBe(true);
  });
  test("only accepts bounded text source formats", () => {
    expect(uploadError("notes.md", 1024)).toBeNull();
    expect(uploadError("notes.csv", 262144)).toBeNull();
    expect(uploadError("report.pdf", 10)).toContain("TXT");
    expect(uploadError("notes.txt", 262145)).toContain("too large");
  });
  test("does not turn unsafe Markdown links into executable navigation", () => {
    expect(safeLink("https://example.com/readme")).toBe("https://example.com/readme");
    for (const value of ["javascript:alert(1)", "data:text/html,evil", "//example.com", "/api/workspace/session"]) expect(safeLink(value)).toBeUndefined();
  });
});
