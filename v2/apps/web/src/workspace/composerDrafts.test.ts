// @vitest-environment jsdom
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {ComposerDrafts, composerKey} from "./composerDrafts";
beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());
test("composer drafts persist by workspace without copying another project's text", () => {
  const drafts = new ComposerDrafts(); drafts.write("alpha", "Alpha private draft"); drafts.write("beta", "Beta notes");
  expect(drafts.load("alpha").draft.content).toBe("Alpha private draft"); expect(drafts.load("beta").draft.content).toBe("Beta notes");
  expect(new ComposerDrafts().load("beta").draft.content).toBe("Beta notes"); expect(new ComposerDrafts().load("fresh").draft.content).toBe("");
});
test("empty/sent drafts remove only their own storage and increment the stale-response fence", () => {
  const drafts = new ComposerDrafts(); const old = drafts.write("alpha", "Submitted text").draft.revision;
  const cleared = drafts.write("alpha", "").draft.revision; expect(cleared).toBeGreaterThan(old); expect(localStorage.getItem(composerKey("alpha"))).toBeNull();
  drafts.write("alpha", "A newer draft"); expect(drafts.revision("alpha")).toBeGreaterThan(cleared); expect(drafts.load("alpha").draft.content).toBe("A newer draft");
});
test("deletion forgets memory and persistent draft, preserving another workspace", () => {
  const drafts = new ComposerDrafts(); drafts.write("alpha", "forget"); drafts.write("beta", "keep"); expect(drafts.forget("alpha")).toBe(true);
  expect(drafts.load("alpha").draft.content).toBe(""); expect(drafts.load("beta").draft.content).toBe("keep");
});
test("storage failure retains a truthful in-tab draft rather than throwing or claiming it saved", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new Error("unavailable");}); const drafts = new ComposerDrafts();
  expect(drafts.write("alpha", "in-tab only").stored).toBe(false); expect(drafts.load("alpha").draft.content).toBe("in-tab only"); expect(drafts.load("alpha").stored).toBe(false);
});
test("failed remove stores an empty tombstone so sent content cannot return on reload", () => {
  const drafts = new ComposerDrafts(); drafts.write("alpha", "old sent text"); vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {throw new Error("remove blocked");});
  expect(drafts.write("alpha", "").stored).toBe(true); expect(new ComposerDrafts().load("alpha").draft.content).toBe("");
});
test("failure of both clear mechanisms is exposed even when the current draft is empty", () => {
  const drafts = new ComposerDrafts(); drafts.write("alpha", "old text"); vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {throw new Error("blocked");}); vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new Error("blocked");});
  const value = drafts.write("alpha", ""); expect(value.draft.content).toBe(""); expect(value.stored).toBe(false);
});
test("malformed or unrelated cached content never becomes a composer draft", () => {
  localStorage.setItem(composerKey("bad"), '{"content":97120,"revision":0}'); localStorage.setItem(composerKey("huge"), JSON.stringify({content:"x".repeat(16001), revision:1}));
  const drafts = new ComposerDrafts(); expect(drafts.load("bad").draft.content).toBe(""); expect(drafts.load("huge").draft.content).toBe("");
});
