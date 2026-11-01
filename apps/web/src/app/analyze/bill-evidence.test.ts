import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { BillReadingNote, BillSourceHint } from "../../components/bill-evidence";
import type { BillEvidence } from "../../lib/bill-import";

const hint = (overrides: Partial<Parameters<typeof BillSourceHint>[0]> = {}) =>
  renderToStaticMarkup(createElement(BillSourceHint, { id: "usage-source", source: { kind: "printed", page: 7 },
    changed: false, empty: false, required: true, reviewed: false, ...overrides }));
const reading = (type: BillEvidence["reading_type"]) => renderToStaticMarkup(createElement(BillReadingNote, {
  evidence: { schema_version: 1, reading_type: type, reading_type_page: type === "unknown" ? null : 3,
    fields: {} as BillEvidence["fields"] },
}));

describe("bill evidence review", () => {
  it("does not attach a model source page to a manually edited value", () => {
    for (const reviewed of [false, true]) {
      const markup = hint({ changed: true, reviewed });
      expect(markup).not.toContain("page 7");
      expect(markup).toContain(reviewed ? "Your edit" : "Edited by you");
    }
  });
  it("keeps required empty fields unresolved even when the review checkbox is checked", () => {
    const markup = hint({ empty: true, reviewed: true });
    expect(markup).toContain("Enter this value");
    expect(markup).not.toContain("Reviewed by you");
    expect(markup).toContain('id="usage-source"');
  });
  it("keeps missing optional charges unknown instead of suggesting zero", () => {
    const markup = hint({ source: { kind: "missing", page: null }, empty: true, required: false });
    expect(markup).toContain("Leave blank if unknown");
    expect(markup).not.toContain("page null");
    expect(markup).not.toContain("0");
  });
  it("distinguishes unresolved extraction from a user's review without claiming verification", () => {
    expect(hint({ source: { kind: "unclear", page: 2 } })).toContain("Needs clarification");
    const reviewed = hint({ source: { kind: "unclear", page: 2 }, reviewed: true });
    expect(reviewed).toContain("Reviewed by you");
    expect(reviewed).toContain("unverified");
    expect(reviewed).not.toContain("Needs clarification");
  });
  it("explains date conversion rather than describing a derived date as printed", () => {
    const markup = hint({ source: { kind: "derived", page: 2 } });
    expect(markup).toContain("exclusive end");
    expect(markup).toContain("date conversion");
  });
  it("qualifies estimated and mixed readings before interpreting consumption changes", () => {
    expect(reading("estimated")).toContain("usage may be estimated");
    expect(reading("mixed")).toContain("which billing readings were measured");
    expect(reading("actual")).toContain("not independent verification");
  });
  it("never invents a source page or reading type for unknown and legacy imports", () => {
    for (const markup of [reading("unknown"), renderToStaticMarkup(createElement(BillReadingNote))]) {
      expect(markup).toContain("Reading type not identified");
      expect(markup).not.toContain("suggested page");
    }
  });
});
