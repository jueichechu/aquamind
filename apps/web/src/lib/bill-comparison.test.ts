import { describe, expect, it } from "vitest";
import corpus from "../../../../evals/fixtures/bill-comparison-contract-v1.json";
import { createBillComparisonEntries, parseBillComparisonResult } from "./bill-comparison";
import type { BillDraft } from "./bills";

const sample = corpus.cases[0];
const response = () => structuredClone(sample.response) as Record<string, unknown>;
const entries = () => createBillComparisonEntries(sample.drafts);

describe("bill comparison browser contract", () => {
  it.each(corpus.cases)("accepts the actual offline API response: $name", ({ drafts, response }) => {
    const submitted = createBillComparisonEntries(drafts);
    const result = parseBillComparisonResult(response, submitted);
    expect(result).toMatchObject({ source: "manual_entry", evidence_level: "historical_bills", confidence: "limited",
      covered_days: response.covered_days, gap_days: response.gap_days,
      baseline_bill_count: response.baseline_bill_count, baseline_billing_days: response.baseline_billing_days,
      baseline_us_gallons_per_day: response.baseline_us_gallons_per_day,
      latest_us_gallons_per_day_change: response.latest_us_gallons_per_day_change,
      latest_percent_change: response.latest_percent_change });
    expect(result.bills.map((value) => value.bill)).toEqual(submitted);
    expect(result.bills.map((value) => value.total_us_gallons)).toEqual(response.bills.map((value) => value.total_us_gallons));
    expect(result.bills.map((value) => value.water_and_sewer_subtotal)).toEqual(response.bills.map((value) => value.water_and_sewer_subtotal));
    expect(result).not.toHaveProperty("limitations");
    expect(result).not.toHaveProperty("request_id");
  });

  it("sorts independent snapshots without changing caller order or decimal text", () => {
    const drafts = structuredClone(sample.drafts);
    const before = structuredClone(drafts);
    const submitted = createBillComparisonEntries(drafts);
    expect(drafts).toEqual(before);
    expect(submitted.map((bill) => bill.period_start)).toEqual(["2024-01-01", "2024-02-01", "2024-04-01"]);
    expect(submitted[0].usage).toBe("03100.00");
    expect(submitted[0].sewer_charge).toBeNull();
    expect(submitted[2].water_charge).toBe("0");
    drafts[1].usage = "999";
    drafts.reverse();
    expect(submitted[0].usage).toBe("03100.00");
  });

  it("rejects invalid counts, overlapping periods and bad individual fields before transport", () => {
    const first = sample.drafts[0];
    for (const drafts of [[], [first], Array(13).fill(first), [first, first],
      [first, { ...first, period_start: "2024-04-02" }],
      [first, { ...sample.drafts[1], usage_unit: "gallons" }],
      [first, { ...sample.drafts[1], period_start: "2026-02-29" }],
      [first, { ...sample.drafts[1], water_charge: "0", currency: "" }],
      [first, { ...sample.drafts[1], usage: "1e6" }]]) {
      expect(() => createBillComparisonEntries(drafts)).toThrow();
    }
    expect(() => createBillComparisonEntries(null as unknown as BillDraft[])).toThrow("2 and 12");
    expect(() => createBillComparisonEntries(Array(2) as BillDraft[])).toThrow();
    expect(createBillComparisonEntries(corpus.cases[4].drafts)).toHaveLength(12);
  });

  it("rejects wrong evidence labels, coverage, baseline counts and unsafe numeric fields", () => {
    const submitted = entries();
    for (const changes of [
      { source: "meter" }, { evidence_level: "interval_meter" }, { confidence: "verified" },
      { request_id: undefined }, { request_id: "bad" },
      { covered_days: 121 }, { gap_days: 0 }, { baseline_bill_count: 3 }, { baseline_billing_days: 90 },
      { baseline_billing_days: "60" }, { bills: null }, { bills: [] },
      { baseline_us_gallons_per_day: "1e3" }, { baseline_us_gallons_per_day: 148.333333 },
      { baseline_us_gallons_per_day: "-1.000000" }, { baseline_us_gallons_per_day: "1000000.000001" },
      { latest_us_gallons_per_day_change: "NaN" }, { latest_us_gallons_per_day_change: "-0.000000" },
      { latest_us_gallons_per_day_change: "-1000000.000001" },
      { latest_percent_change: "-100.01" }, { latest_percent_change: "1e17" },
      { latest_percent_change: "-0.00" }, { latest_percent_change: "140000000000000001.00" },
      { latest_percent_change: null }, { latest_percent_change: 34.83 },
    ]) expect(() => parseBillComparisonResult({ ...response(), ...changes }, submitted)).toThrow("invalid comparison");
    for (const invalid of [null, [], true, "private-value"]) {
      expect(() => parseBillComparisonResult(invalid, submitted)).toThrow("invalid comparison");
    }
  });

  it("binds every normalized entry in chronological order and rejects mismatched values", () => {
    for (const mutate of [
      (bills: Record<string, unknown>[]) => bills.reverse(),
      (bills: Record<string, unknown>[]) => { bills[1] = bills[0]; },
      (bills: Record<string, unknown>[]) => { bills[0].source = "ai_verified"; },
      (bills: Record<string, unknown>[]) => { bills[0].billing_days = 32; },
      (bills: Record<string, unknown>[]) => { bills[0].total_us_gallons = "Infinity"; },
      (bills: Record<string, unknown>[]) => { bills[0].water_and_sewer_subtotal = "0.00"; },
      (bills: Record<string, unknown>[]) => { (bills[0].bill as Record<string, unknown>).usage = "999"; },
      (bills: Record<string, unknown>[]) => { (bills[0].bill as Record<string, unknown>).usage_unit = "ccf"; },
    ]) {
      const value = response();
      mutate(value.bills as Record<string, unknown>[]);
      expect(() => parseBillComparisonResult(value, entries())).toThrow("invalid comparison");
    }
  });

  it("distinguishes true zero from a positive baseline that rounds to display zero", () => {
    const exactZero = corpus.cases[1];
    const positive = corpus.cases[2];
    expect(parseBillComparisonResult(exactZero.response, createBillComparisonEntries(exactZero.drafts)).latest_percent_change).toBeNull();
    expect(() => parseBillComparisonResult({ ...exactZero.response, latest_percent_change: "0.00" },
      createBillComparisonEntries(exactZero.drafts))).toThrow("invalid comparison");
    expect(positive.response.baseline_us_gallons_per_day).toBe("0.000000");
    expect(parseBillComparisonResult(positive.response, createBillComparisonEntries(positive.drafts)).latest_percent_change)
      .toBe(positive.response.latest_percent_change);
    expect(() => parseBillComparisonResult({ ...positive.response, latest_percent_change: null },
      createBillComparisonEntries(positive.drafts))).toThrow("invalid comparison");
  });

  it("returns independent data and discards untrusted extra fields", () => {
    const submitted = entries();
    const value = response();
    const result = parseBillComparisonResult({ ...value, leak_probability: 0.99, arbitrary_text: "private" }, submitted);
    submitted[0].usage = "777";
    (value.bills as unknown[]).length = 0;
    expect(result.bills).toHaveLength(3);
    expect(result.bills[0].bill.usage).toBe("03100.00");
    expect(result).not.toHaveProperty("leak_probability");
    expect(result).not.toHaveProperty("arbitrary_text");
  });
});
