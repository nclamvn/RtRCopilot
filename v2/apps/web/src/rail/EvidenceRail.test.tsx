// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {cleanup, render, screen} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import {I18nProvider} from "../i18n/provider";
import {evidenceFromAskCitation, evidenceFromResearchHit} from "./contracts";
import {EvidenceRail, locatorText} from "./EvidenceRail";
import {MESSAGES} from "../i18n/messages";

afterEach(cleanup);

const versionId = "22222222-2222-4222-8222-222222222222";
const sha = "a".repeat(64);

const askEntry = evidenceFromAskCitation({
  marker: "C1",
  chunk_id: "11111111-1111-4111-8111-111111111111",
  record_key: "company.warranty",
  record_version_id: versionId,
  evidence_key: "company.warranty.e1",
  record_checksum: sha,
  evidence_checksum: "b".repeat(64),
  source_key: "rtr.specs",
  source_revision: 3,
  provenance_level: "approved_internal",
  verification_state: "approved",
  freshness_state: "current",
  source_label: "Company specification",
  locator: {page: 4},
  redacted: false,
}, "grounded");

const redactedEntry = evidenceFromAskCitation({
  marker: "C2",
  chunk_id: "44444444-4444-4444-8444-444444444444",
  record_key: "company.pricing",
  record_version_id: "55555555-5555-4555-8555-555555555555",
  evidence_key: null,
  record_checksum: sha,
  evidence_checksum: null,
  source_key: "rtr.specs",
  source_revision: 3,
  provenance_level: "approved_internal",
  verification_state: "approved",
  freshness_state: "current",
  source_label: "Pricing sheet",
  locator: {sheet: "Data", cell: "B7"},
  redacted: true,
}, "grounded");

const researchEntry = evidenceFromResearchHit({
  zone_label: "research",
  research_record_id: "33333333-3333-4333-8333-333333333333",
  record_key: "vendor.abb.profile",
  tier: "P",
  snippet: "ABB manufactures industrial robots.",
  lexical_score: 0.8,
  citation: {
    zone_label: "research",
    research_record_id: "33333333-3333-4333-8333-333333333333",
    record_key: "vendor.abb.profile",
    version_ordinal: 1,
    tier: "P",
    source_key: "refinery.industry",
    package_fingerprint: sha,
    content_sha256: "c".repeat(64),
    corroboration_state: "corroborated",
    evidence_checksums: ["d".repeat(64)],
  },
});

test("renders entries with server-provided chips, checksums and locator links", () => {
  render(<EvidenceRail entries={[askEntry, researchEntry]} activeKey="C1"/>);
  const rail = screen.getByRole("complementary", {name: "Bằng chứng & xuất xứ"});
  expect(rail).toHaveAttribute("data-shell-region");
  // Ask citation: no server zone label → no chip, explicit accessible text.
  expect(screen.getByText("[C1]")).toBeInTheDocument();
  expect(screen.getByText("Không có nhãn vùng từ máy chủ")).toBeInTheDocument();
  expect(screen.getByText("Sự thật SOT (grounded)")).toBeInTheDocument();
  // Research entry: chip renders exactly the server label.
  expect(screen.getAllByText("RESEARCH").length).toBeGreaterThanOrEqual(1);
  expect(screen.queryByText("SOT", {exact: true})).toBeNull();
  expect(screen.getByText("Do nghiên cứu hỗ trợ (research_supported)")).toBeInTheDocument();
  expect(screen.getByTitle(sha)).toBeInTheDocument();
  const locatorLink = screen.getByRole("link", {name: "Mở đúng vị trí — Trang 4"});
  expect(locatorLink).toHaveAttribute("href", `/files?version=${versionId}&page=4`);
  expect(screen.getByText("Không có định vị sâu")).toBeInTheDocument();
  const active = document.getElementById("rail-entry-C1");
  expect(active).toHaveAttribute("aria-current", "true");
  expect(active).toHaveAttribute("tabindex", "-1");
});

test("policy state renders the DLP redaction and the activation callback fires", () => {
  const onActivate = vi.fn();
  render(<EvidenceRail entries={[redactedEntry]} onActivateLocator={onActivate}/>);
  expect(screen.getByText("DLP đã che một phần")).toBeInTheDocument();
  expect(screen.getByText("DLP")).toBeInTheDocument();
  const link = screen.getByRole("link", {name: "Mở đúng vị trí — Bảng Data · Ô B7"});
  link.addEventListener("click", event => event.preventDefault());
  link.click();
  expect(onActivate).toHaveBeenCalledTimes(1);
  expect(onActivate.mock.calls[0][0].key).toBe("C2");
});

test("empty state and mobile close render; English locale is complete", () => {
  const onClose = vi.fn();
  render(<I18nProvider initialLocale="en">
    <EvidenceRail entries={[]} open onClose={onClose}/>
  </I18nProvider>);
  expect(screen.getByRole("complementary", {name: "Evidence & provenance"}))
    .toHaveClass("open");
  expect(screen.getByText("No evidence to show yet.")).toBeInTheDocument();
  screen.getByRole("button", {name: "Close evidence"}).click();
  expect(onClose).toHaveBeenCalled();
});

test("locator accessible text covers every rtr.locator.v1 member", () => {
  const t = (key: keyof typeof MESSAGES.vi) => MESSAGES.vi[key];
  expect(locatorText({page: 4}, t, "vi")).toBe("Trang 4");
  expect(locatorText({sheet: "Data", cell: "B7"}, t, "vi")).toBe("Bảng Data · Ô B7");
  expect(locatorText({slide: 3}, t, "vi")).toBe("Slide 3");
  expect(locatorText({t: 12_500}, t, "vi")).toBe("Mốc 12,5s");
  expect(locatorText({paragraph: 2}, t, "vi")).toBe("Đoạn 2");
  expect(locatorText(null, t, "vi")).toBe("Toàn tệp");
});
