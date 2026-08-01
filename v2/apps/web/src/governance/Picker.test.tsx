// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import {PickerCombobox, PickerSelection} from "./Picker";

const id = (n: string) =>
  `${n.repeat(8)}-${n.repeat(4)}-4${n.repeat(3)}-8${n.repeat(3)}-${n.repeat(12)}`;

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status, headers: {"content-type": "application/json"},
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function stubFetch(handler: (url: string) => Response) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    return handler(url);
  }));
  return calls;
}

test("subject picker: debounced bounded search renders options; ArrowDown+Enter selects", async () => {
  const calls = stubFetch(() => json({
    items: [
      {subject_id: id("1"), display_name: "RtR Curator", email: "c@rtrobotics.com"},
      {subject_id: id("2"), display_name: "RtR Staff", email: null},
    ],
    next_cursor: null,
  }));
  const selected: Array<PickerSelection | null> = [];
  render(<PickerCombobox kind="subjects" value={null}
    onSelect={item => selected.push(item)} onSessionLost={() => undefined}/>);
  const input = screen.getByRole("combobox", {name: "Người phụ trách"});
  fireEvent.focus(input);
  // No fetch before a query is typed — only the hint shows.
  expect(screen.getByText("Nhập để tìm trong phạm vi được cấp quyền.")).toBeInTheDocument();
  expect(calls).toHaveLength(0);
  fireEvent.change(input, {target: {value: "RtR"}});
  await waitFor(() => expect(
    screen.getAllByRole("option").length).toBe(2));
  expect(calls).toHaveLength(1);
  expect(calls[0]).toBe(
    "/api/governance/governance/pickers/subjects?query=RtR&limit=8");
  expect(screen.getByText("c@rtrobotics.com")).toBeInTheDocument();
  // First option is highlighted; ArrowDown moves to the second; Enter selects.
  expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(input, {key: "ArrowDown"});
  expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(input, {key: "Enter"});
  expect(selected).toEqual([{id: id("2"), label: "RtR Staff"}]);
  expect(screen.queryByRole("listbox")).toBeNull();
});

test("selected value renders with a clear affordance", () => {
  stubFetch(() => json({items: [], next_cursor: null}));
  const selected: Array<PickerSelection | null> = [];
  render(<PickerCombobox kind="subjects"
    value={{id: id("1"), label: "RtR Curator"}}
    onSelect={item => selected.push(item)} onSessionLost={() => undefined}/>);
  expect(screen.getByText("RtR Curator")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Bỏ chọn"}));
  expect(selected).toEqual([null]);
});

test("typed denied and error states render code · request_id; empty renders scoped message", async () => {
  const responses: Record<string, Response> = {};
  stubFetch(url => {
    if (url.includes("query=denied")) {
      return json({error: {code: "curator_required", message: ""},
        request_id: "req-403"}, 403);
    }
    if (url.includes("query=boom")) {
      return json({error: {code: "governance_service_unavailable", message: ""},
        request_id: "req-503"}, 503);
    }
    return json({items: [], next_cursor: null});
  });
  void responses;
  render(<PickerCombobox kind="subjects" value={null}
    onSelect={() => undefined} onSessionLost={() => undefined}/>);
  const input = screen.getByRole("combobox", {name: "Người phụ trách"});
  fireEvent.change(input, {target: {value: "denied"}});
  await waitFor(() => expect(screen.getByRole("alert"))
    .toHaveTextContent("curator_required · req-403"));
  expect(screen.getByRole("alert")).toHaveTextContent("Bị từ chối theo chính sách");
  fireEvent.change(input, {target: {value: "boom"}});
  await waitFor(() => expect(screen.getByRole("alert"))
    .toHaveTextContent("governance_service_unavailable · req-503"));
  fireEvent.change(input, {target: {value: "nothing"}});
  await waitFor(() => expect(
    screen.getByText("Không có kết quả trong phạm vi được cấp quyền."))
    .toBeInTheDocument());
});

test("401 during search drops the session via onSessionLost", async () => {
  stubFetch(() => json({error: {code: "authentication_required"}}, 401));
  const lost = vi.fn();
  render(<PickerCombobox kind="subjects" value={null}
    onSelect={() => undefined} onSessionLost={lost}/>);
  fireEvent.change(screen.getByRole("combobox", {name: "Người phụ trách"}),
    {target: {value: "x"}});
  await waitFor(() => expect(lost).toHaveBeenCalled());
});

test("record picker renders SOT chips from the literal server label and supports the raw-UUID fallback", async () => {
  stubFetch(() => json({
    items: [{
      zone_label: "sot", record_key: "company.warranty",
      record_version_id: id("3"), title: "Bảo hành robot",
      classification: "internal",
    }],
    next_cursor: null,
  }));
  const selected: Array<PickerSelection | null> = [];
  render(<PickerCombobox kind="records" value={null}
    onSelect={item => selected.push(item)} onSessionLost={() => undefined}/>);
  const input = screen.getByRole("combobox", {name: "Bản ghi SOT trả lời"});
  fireEvent.change(input, {target: {value: "warranty"}});
  await waitFor(() => expect(screen.getAllByRole("option").length).toBe(1));
  const option = screen.getAllByRole("option")[0];
  expect(option.querySelector(".zone-chip.zone-sot")).not.toBeNull();
  expect(option).toHaveTextContent("company.warranty");
  fireEvent.keyDown(input, {key: "Enter"});
  expect(selected).toEqual([{id: id("3"), label: "company.warranty"}]);
  // A UUID-shaped query offers the raw fallback option first.
  fireEvent.change(input, {target: {value: id("7")}});
  await waitFor(() => expect(screen.getAllByRole("option").length).toBe(2));
  expect(screen.getAllByRole("option")[0])
    .toHaveTextContent("Dùng UUID này trực tiếp");
  fireEvent.keyDown(input, {key: "Enter"});
  expect(selected[1]).toEqual({id: id("7"), label: id("7")});
});

test("a forged zone label on a record picker row rejects the whole page as a typed error", async () => {
  stubFetch(() => json({
    items: [{
      zone_label: "research", record_key: "company.warranty",
      record_version_id: id("3"), title: null, classification: "internal",
    }],
    next_cursor: null,
  }));
  render(<PickerCombobox kind="records" value={null}
    onSelect={() => undefined} onSessionLost={() => undefined}/>);
  fireEvent.change(screen.getByRole("combobox", {name: "Bản ghi SOT trả lời"}),
    {target: {value: "warranty"}});
  await waitFor(() => expect(screen.getByRole("alert"))
    .toHaveTextContent("contract_violation"));
  expect(screen.queryByRole("option")).toBeNull();
});
