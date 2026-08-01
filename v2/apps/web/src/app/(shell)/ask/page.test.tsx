// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {cleanup, render, screen} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test} from "vitest";
import {I18nProvider} from "../../../i18n/provider";
import AskPage from "./page";

afterEach(cleanup);

test("ask placeholder renders exactly one H1 in Vietnamese by default", () => {
  render(<AskPage/>);
  const headings = screen.getAllByRole("heading", {level: 1});
  expect(headings.length).toBe(1);
  expect(headings[0]).toHaveTextContent("Hỏi");
  expect(screen.getByText(/Sắp có/)).toBeInTheDocument();
});

test("ask placeholder is fully translated under the en locale", () => {
  render(<I18nProvider initialLocale="en"><AskPage/></I18nProvider>);
  expect(screen.getByRole("heading", {level: 1, name: "Ask"})).toBeInTheDocument();
  expect(screen.getByText(/Coming soon/)).toBeInTheDocument();
  expect(screen.queryByText(/Sắp có/)).toBeNull();
});
