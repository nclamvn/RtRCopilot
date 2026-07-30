// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {render, screen} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import Home from "./page";

afterEach(() => vi.restoreAllMocks());

test("states honestly that the foundation has no data", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
  render(<Home/>);
  expect(screen.getByText(/chưa có dữ liệu/i)).toBeInTheDocument();
  expect(screen.queryByText(/^Ask$/)).not.toBeInTheDocument();
});
