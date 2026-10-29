// @vitest-environment jsdom
import {beforeEach, expect, test, vi} from "vitest";
import {contextIdentity, emptyContext, WorkspaceContextChoices} from "./contextChoices";
beforeEach(() => {localStorage.clear(); vi.restoreAllMocks();});
test("context choices remain workspace-scoped across reload without storing source content", () => {
  const choices = new WorkspaceContextChoices();
  choices.save("alpha", {references: [{kind: "file", id: "file-a"}], target: {kind: "artifact", id: "output-a", version: 2}});
  expect(choices.load("beta")).toEqual(emptyContext());
  expect(new WorkspaceContextChoices().load("alpha")).toEqual({references: [{kind: "file", id: "file-a"}], target: {kind: "artifact", id: "output-a", version: 2}});
  choices.forget("alpha"); expect(new WorkspaceContextChoices().load("alpha")).toEqual(emptyContext());
});
test("context identity binds reference ordering, artifact version and target exactly like the server", () => {
  const a = {references: [{kind: "file" as const, id: "f"}, {kind: "artifact" as const, id: "a", version: 1}], target: null};
  expect(contextIdentity(a)).not.toBe(contextIdentity({...a, references: [...a.references].reverse()}));
  expect(contextIdentity(a)).not.toBe(contextIdentity({...a, target: {kind: "artifact", id: "a", version: 2}}));
});
test("malformed cached references never become executable context", () => {
  for (const value of [{references: [{kind: "shell", id: "sh"}], target: null}, {references: [{kind: "file", id: "../escape"}], target: null}, {references: [], target: {kind: "file", id: "f"}}, {references: Array(21).fill({kind: "file", id: "f"}), target: null}]) {
    localStorage.setItem("agent-workspace:context:invalid", JSON.stringify(value)); expect(new WorkspaceContextChoices().load("invalid")).toEqual(emptyContext());
  }
});
test("storage failure preserves in-tab choices and reports that they are not durable", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new Error("synthetic blocked storage");});
  const choices = new WorkspaceContextChoices(), value = {references: [{kind: "file" as const, id: "one"}], target: null};
  expect(choices.save("one", value)).toBe(false); expect(choices.load("one")).toEqual(value); expect(choices.load("two")).toEqual(emptyContext()); expect(choices.load("one")).toEqual(value); expect(choices.isStored("one")).toBe(false);
});
test("AW08 optional review choice binds request identity and reload only with exact artifact target", () => {
  const selected = {references: [], target: {kind: "artifact" as const, id: "artifact-one", version: 2}}; expect(contextIdentity(selected)).not.toBe(contextIdentity({...selected, review_edits: true})); expect(contextIdentity(selected)).toBe(contextIdentity({...selected, review_edits: false})); const choices = new WorkspaceContextChoices(); choices.save("review", {...selected, review_edits: true}); expect(new WorkspaceContextChoices().load("review")).toEqual({...selected, review_edits: true}); localStorage.setItem("agent-workspace:context:no-target", JSON.stringify({references: [], target: null, review_edits: true})); expect(new WorkspaceContextChoices().load("no-target")).toEqual(emptyContext());
});
