import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import type { BillEvidence } from "../../lib/bill-import";
import type { BillDraft } from "../../lib/bills";
import { BillEntry } from "./bill-entry";

it("connects imported source hints accessibly while preserving manual entry and required review", () => {
  const draft: BillDraft = { period_start: "2026-06-01", period_end_exclusive: "2026-07-01", usage: "8.5",
    usage_unit: "", water_charge: "45.12", sewer_charge: "", currency: "USD" };
  const evidence: BillEvidence = { schema_version: 1, reading_type: "estimated", reading_type_page: 1,
    fields: Object.fromEntries(Object.entries(draft).map(([key, value]) =>
      [key, { kind: value ? "printed" : "missing", page: value ? 1 : null }])) as BillEvidence["fields"] };
  evidence.fields.usage_unit = { kind: "unclear", page: 1 };
  const markup = renderToStaticMarkup(<BillEntry initialDraft={draft} imported evidence={evidence} />);
  for (const field of Object.keys(draft)) {
    expect(markup).toContain(`id="bill-${field}-source"`);
    expect(markup).toMatch(new RegExp(`aria-describedby="[^"]*bill-${field}-source`));
  }
  expect(markup).toContain('aria-describedby="bill-end-help bill-period_end_exclusive-source"');
  const label = markup.match(/<label[^>]*for="bill-usage">([\s\S]*?)<\/label>/)?.[1];
  expect(label).toContain("Total water usage");
  expect(label).not.toMatch(/Suggested source|Needs clarification|Reviewed by you/);
  expect(markup).toContain("Enter this value from your report (suggested page 1)");
  expect(markup).toMatch(/<button[^>]*disabled=""[^>]*>Calculate bill usage<\/button>/);
  expect(markup).not.toMatch(/<input[^>]*type="checkbox"[^>]*checked/);
  const manual = renderToStaticMarkup(<BillEntry />);
  expect(manual).not.toContain("Suggested source");
  expect(manual).not.toContain("bill-period_start-source");
  expect(manual).not.toContain("Bill marked as estimated");
  const legacy = renderToStaticMarkup(<BillEntry initialDraft={draft} imported />);
  expect(legacy).toContain("Reading type not identified");
  expect(legacy).not.toContain("bill-period_start-source");
});
