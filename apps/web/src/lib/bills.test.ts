import { describe, expect, it } from "vitest";
import { createBillEntry, parseBillResult, type BillDraft } from "./bills";

const draft: BillDraft = { period_start: "2026-06-01", period_end_exclusive: "2026-07-01", usage: "3000",
  usage_unit: "us_gallons", water_charge: "", sewer_charge: "", currency: "" };
const response = () => ({ source: "manual_entry", evidence_level: "bill_only", confidence: "limited",
  request_id: "12345678-abcd-1234-abcd-123456789abc", bill: createBillEntry(draft), billing_days: 30,
  total_us_gallons: "3000.000000", us_gallons_per_day: "100.000000", water_and_sewer_subtotal: null });

describe("manual bill browser contract", () => {
  it("requires an explicit unit and preserves decimal text without guessing missing charges", () => {
    for (const unit of ["us_gallons", "ccf", "cubic_meters", "liters"]) {
      expect(createBillEntry({ ...draft, usage_unit: unit, usage: " 0008.500001 " })).toMatchObject({
        usage: "0008.500001", usage_unit: unit, water_charge: null, sewer_charge: null, currency: null,
      });
    }
    for (const unit of ["", "gallons", "imperial_gallons", "constructor", "__proto__"]) {
      expect(() => createBillEntry({ ...draft, usage_unit: unit })).toThrow("unit");
    }
  });

  it("distinguishes blank charges from zero and requires explicit USD for any entered charge", () => {
    expect(createBillEntry({ ...draft, water_charge: " 0.00 ", currency: "USD" })).toMatchObject({
      water_charge: "0.00", sewer_charge: null, currency: "USD",
    });
    for (const changes of [{ water_charge: "0" }, { sewer_charge: "0.00" }, { currency: "CAD" },
      { water_charge: "1.234", currency: "USD" }, { water_charge: "1000000.01", currency: "USD" }]) {
      expect(() => createBillEntry({ ...draft, ...changes })).toThrow();
    }
  });

  it("validates real calendar dates, leap years and exclusive periods independently of local time", () => {
    for (const changes of [
      { period_start: "2026-02-29" }, { period_start: "2026-04-31" }, { period_start: "0000-01-01" },
      { period_start: "2026-06-01T00:00:00Z" }, { period_end_exclusive: "2026-06-01" },
      { period_end_exclusive: "2026-05-31" }, { period_end_exclusive: "2027-06-03" },
    ]) expect(() => createBillEntry({ ...draft, ...changes })).toThrow("billing dates");
    const entry = createBillEntry({ ...draft, period_start: "2024-02-29", period_end_exclusive: "2025-03-01" });
    expect(parseBillResult({ ...response(), bill: entry, billing_days: 366 }, entry).billing_days).toBe(366);
    const dst = createBillEntry({ ...draft, period_start: "2026-03-08", period_end_exclusive: "2026-03-09" });
    expect(parseBillResult({ ...response(), bill: dst, billing_days: 1 }, dst).billing_days).toBe(1);
  });

  it("rejects ambiguous, negative, exponential and over-precision amounts", () => {
    for (const usage of ["-1", "NaN", "Infinity", "1,000", "1e3", "1 gallon", "1.0000001", "1000000000", ".5", ""]) {
      expect(() => createBillEntry({ ...draft, usage })).toThrow("usage");
    }
    expect(createBillEntry({ ...draft, usage: "0" }).usage).toBe("0");
    expect(createBillEntry({ ...draft, usage: "0.000001" }).usage).toBe("0.000001");
  });

  it("allows equivalent returned decimal spellings while binding results to the entered bill", () => {
    const entry = createBillEntry({ ...draft, usage: "0003000.00" });
    const parsed = parseBillResult(response(), entry);
    expect(parsed.bill.usage).toBe("0003000.00");
    expect(parsed.total_us_gallons).toBe("3000.000000");
    expect(parsed.water_and_sewer_subtotal).toBeNull();
    for (const changes of [{ usage: "3001" }, { usage_unit: "ccf" }, { currency: "USD" },
      { water_charge: "0" }, { period_start: "2026-06-02" }]) {
      expect(() => parseBillResult({ ...response(), bill: { ...response().bill, ...changes } }, entry)).toThrow("invalid result");
    }
  });

  it("rejects unsafe/missing result fields and fabricated charges or stronger evidence", () => {
    const entry = createBillEntry(draft);
    for (const changes of [{ source: "synthetic" }, { confidence: "strong" }, { evidence_level: "interval_meter" },
      { billing_days: 29 }, { total_us_gallons: 3000 }, { total_us_gallons: "NaN" },
      { us_gallons_per_day: "-1.000000" }, { total_us_gallons: "1000000.000001" },
      { request_id: undefined }, { water_and_sewer_subtotal: "0.00" }, { bill: null }]) {
      expect(() => parseBillResult({ ...response(), ...changes }, entry)).toThrow("invalid result");
    }
    const zeroCharges = createBillEntry({ ...draft, water_charge: "0", sewer_charge: "0", currency: "USD" });
    expect(parseBillResult({ ...response(), bill: zeroCharges, water_and_sewer_subtotal: "0.00" }, zeroCharges)
      .water_and_sewer_subtotal).toBe("0.00");
  });
});
