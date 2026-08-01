// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {cleanup, render, screen} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test} from "vitest";
import {I18nProvider} from "../../../i18n/provider";
import AdminPage from "./page";

afterEach(cleanup);

test("admin placeholder renders one H1 and lists the admin API surfaces", () => {
  render(<AdminPage/>);
  const headings = screen.getAllByRole("heading", {level: 1});
  expect(headings.length).toBe(1);
  expect(headings[0]).toHaveTextContent("Quản trị");
  for (const path of [
    "/api/v1/admin/research-sources", "/api/v1/admin/settings",
    "/api/v1/admin/gaps/{gap_id}/priority", "/api/v1/admin/subjects",
    "/api/v1/admin/jobs/health",
  ]) {
    expect(screen.getByText(path)).toBeInTheDocument();
  }
});

test("admin placeholder is fully translated under the en locale", () => {
  render(<I18nProvider initialLocale="en"><AdminPage/></I18nProvider>);
  expect(screen.getByRole("heading", {level: 1, name: "Administration"}))
    .toBeInTheDocument();
  expect(screen.getByText(/No admin UI yet/)).toBeInTheDocument();
});
