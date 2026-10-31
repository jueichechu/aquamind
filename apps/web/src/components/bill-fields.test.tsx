import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { BillFields } from "./bill-fields";

const draft = { period_start: "2026-06-01", period_end_exclusive: "2026-07-01", usage: "8.5",
  usage_unit: "ccf", water_charge: "", sewer_charge: "", currency: "" };

it("gives repeated bill inputs unique labels and local helper references", () => {
  const html = renderToStaticMarkup(<><BillFields idPrefix="first" draft={draft} onChange={() => {}} />
    <BillFields idPrefix="second" draft={draft} onChange={() => {}} /></>);
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  expect(new Set(ids).size).toBe(ids.length);
  for (const prefix of ["first", "second"]) {
    for (const field of ["start", "end", "usage", "unit", "water-charge", "sewer-charge", "currency"]) {
      expect(html).toContain(`for="${prefix}-${field}"`);
      expect(html).toContain(`id="${prefix}-${field}"`);
    }
    expect(html).toContain(`aria-describedby="${prefix}-end-help"`);
    expect(html).toContain(`aria-describedby="${prefix}-usage-help"`);
  }
  expect(html.match(/required=""/g)).toHaveLength(8);
});

it("preserves legacy field IDs, decimal constraints and required currency for zero charges", () => {
  const html = renderToStaticMarkup(<BillFields draft={{ ...draft, water_charge: "0" }} onChange={() => {}} />);
  expect(html).toContain('id="bill-start"');
  expect(html).toContain('maxLength="16"');
  expect(html).toContain('inputMode="decimal"');
  expect(html).toMatch(/<select[^>]*id="bill-currency"[^>]*required=""/);
  expect(html).toContain('value="0"');
  expect(html).toContain("Leave missing charges blank");
});
