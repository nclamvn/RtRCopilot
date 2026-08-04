// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import React from "react";
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {I18nProvider} from "../i18n/provider";
import {AppShell, activeArea, visibleAreas} from "./AppShell";

const nav = vi.hoisted(() => ({
  pathname: "/ask", view: null as string | null, push: vi.fn(),
}));
vi.mock("next/navigation", () => {
  const router = {
    push: nav.push, replace() {}, prefetch() {}, back() {}, forward() {}, refresh() {},
  };
  return {
    usePathname: () => nav.pathname,
    useSearchParams: () => new URLSearchParams(nav.view ? `view=${nav.view}` : ""),
    useRouter: () => router,
  };
});

const identity = {
  user_id: "77777777-7777-4777-8777-777777777777",
  email: "admin@rtrobotics.com", display_name: "RtR Admin", roles: ["admin"],
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status, headers: {"content-type": "application/json"},
  });
}

beforeEach(() => {
  nav.pathname = "/ask";
  nav.view = null;
  nav.push.mockClear();
  vi.stubGlobal("fetch", vi.fn(async () => json(identity)));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.cookie = "rtr_locale=; path=/; max-age=0";
  document.documentElement.lang = "vi";
});

function renderShell(initialLocale: "vi" | "en" = "vi") {
  return render(<I18nProvider initialLocale={initialLocale}>
    <AppShell><h1>Nội dung thử</h1></AppShell>
  </I18nProvider>);
}

test("shell renders topbar, six nav areas and marks the active area", async () => {
  renderShell();
  expect(screen.getAllByText("Copilot")).toHaveLength(1);
  expect(document.querySelector(".pc-topbar .pc-brand")).not.toBeInTheDocument();
  expect(screen.queryByText("Real-time Robotics")).not.toBeInTheDocument();
  const workspace = screen.getByRole("button", {name: "Mở bảng lệnh không gian làm việc"});
  expect(within(workspace).getByText("Copilot")).toBeInTheDocument();
  expect(within(workspace).queryByText("Không gian nội bộ")).not.toBeInTheDocument();
  expect(await screen.findByText("RtR Admin")).toBeInTheDocument();
  const navigation = screen.getByRole("navigation", {name: "Điều hướng chính"});
  const links = [
    ["Hỏi", "/ask"], ["Tệp", "/files"], ["Tài liệu", "/documents"],
    ["Tri thức", "/knowledge-ops?view=research"],
    ["Vận hành", "/knowledge-ops"], ["Quản trị", "/admin"],
  ] as const;
  // Scope to the primary nav: the mobile dock repeats the six names (a second
  // nav) and jsdom ignores its display:none, so unscoped queries would clash.
  for (const [name, href] of links) {
    expect(within(navigation).getByRole("link", {name})).toHaveAttribute("href", href);
  }
  expect(navigation.querySelectorAll("ol a").length).toBe(6);
  expect(within(navigation).getByRole("link", {name: "Hỏi"}))
    .toHaveAttribute("aria-current", "page");
  expect(within(navigation).getByRole("link", {name: "Quản trị"}))
    .not.toHaveAttribute("aria-current");
});

test("active-area rules cover every route, including knowledge-ops views", () => {
  expect(activeArea("/ask", null)).toBe("ask");
  // "/" is a server redirect to /files since TIP-011 Task 3 (never shell-rendered).
  expect(activeArea("/", null)).toBeNull();
  expect(activeArea("/files", null)).toBe("files");
  expect(activeArea("/documents", null)).toBe("documents");
  expect(activeArea("/knowledge-ops", null)).toBe("operations");
  expect(activeArea("/knowledge-ops", "gaps")).toBe("operations");
  expect(activeArea("/knowledge-ops", "freshness")).toBe("operations");
  expect(activeArea("/knowledge-ops", "research")).toBe("knowledge");
  expect(activeArea("/knowledge-ops", "graduation")).toBe("knowledge");
  expect(activeArea("/admin", null)).toBe("admin");
  expect(activeArea("/elsewhere", null)).toBeNull();
});

test("role-scoped information architecture removes privileged dead ends", () => {
  expect(visibleAreas({...identity, roles: ["staff"]}).map(item => item.area))
    .toEqual(["ask", "files", "documents"]);
  expect(visibleAreas({...identity, roles: ["curator"]}).map(item => item.area))
    .toEqual(["ask", "files", "documents", "knowledge", "operations"]);
  expect(visibleAreas(identity).map(item => item.area)).toEqual([
    "ask", "files", "documents", "knowledge", "operations", "admin",
  ]);
});

test("skip link is the first focusable element and moves focus to main", () => {
  const {container} = renderShell();
  const skip = screen.getByRole("link", {name: "Bỏ qua tới nội dung chính"});
  expect(skip).toHaveAttribute("href", "#main");
  expect(container.querySelector("a, button")).toBe(skip);
  fireEvent.click(skip);
  const main = screen.getByRole("main");
  expect(main).toHaveAttribute("id", "main");
  expect(document.activeElement).toBe(main);
});

test("global search opens the command palette", () => {
  renderShell();
  const search = screen.getByRole("button", {name: "Hỏi hoặc tìm trong tri thức công ty"});
  expect(search).toHaveAttribute("aria-haspopup", "dialog");
  fireEvent.click(search);
  expect(screen.getByRole("dialog", {name: "Hỏi hoặc tìm trong tri thức công ty"}))
    .toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", {name: "Hỏi hoặc tìm trong tri thức công ty"}), {
    target: {value: "bảo hành robot"},
  });
  const askAction = screen.getByRole("link", {name: /Hỏi Copilot:.*bảo hành robot/});
  expect(askAction).toBeInTheDocument();
  expect(askAction).toHaveAttribute("href", "/ask?q=b%E1%BA%A3o%20h%C3%A0nh%20robot");
});

test("language switch flips strings, lang attribute and persists via cookie only", async () => {
  renderShell();
  expect(await screen.findByText("RtR Admin")).toBeInTheDocument();
  const en = screen.getByRole("button", {name: "EN"});
  expect(en).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(en);
  expect(en).toHaveAttribute("aria-pressed", "true");
  const navEn = screen.getByRole("navigation", {name: "Primary navigation"});
  expect(within(navEn).getByRole("link", {name: "Ask"})).toBeInTheDocument();
  expect(within(navEn).getByRole("link", {name: "Admin"})).toBeInTheDocument();
  expect(document.documentElement.lang).toBe("en");
  expect(document.cookie).toContain("rtr_locale=en");
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  fireEvent.click(screen.getByRole("button", {name: "VI"}));
  const navVi = screen.getByRole("navigation", {name: "Điều hướng chính"});
  expect(within(navVi).getByRole("link", {name: "Hỏi"})).toBeInTheDocument();
  expect(document.documentElement.lang).toBe("vi");
  expect(document.cookie).toContain("rtr_locale=vi");
});

test("F6 and Shift+F6 cycle focus between navigation and work surface", () => {
  renderShell();
  const navigation = screen.getByRole("navigation", {name: "Điều hướng chính"});
  const main = screen.getByRole("main");
  fireEvent.keyDown(window, {key: "F6"});
  expect(document.activeElement).toBe(navigation);
  fireEvent.keyDown(window, {key: "F6"});
  expect(document.activeElement).toBe(main);
  fireEvent.keyDown(window, {key: "F6", shiftKey: true});
  expect(document.activeElement).toBe(navigation);
});

test("anonymous session renders the company sign-in affordance", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(
    {error: {code: "authentication_required"}}, 401,
  )));
  renderShell();
  expect(await screen.findByRole("link", {name: "Đăng nhập công ty"}))
    .toHaveAttribute("href", "/api/auth/login");
});

test("answer-quality setup debt is visible while core services remain healthy", async () => {
  vi.stubGlobal("fetch", vi.fn(async input => {
    const url = String(input);
    if (url === "/api/status") return json({
      ok: true,
      status: "operational",
      answer_quality: "configuration_required",
    });
    if (url === "/api/auth/me") return json(identity);
    return json({items: []});
  }));
  renderShell();
  await waitFor(() => expect(
    screen.getByText("Cần cấu hình API chất lượng trả lời"),
  ).toBeInTheDocument());
  expect(screen.getByText("LLM")).toBeInTheDocument();
});
