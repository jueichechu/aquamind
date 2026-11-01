import { createBillEntry, parseBillResult, type BillDraft, type BillResult, type ManualBill } from "./bills";

export type BillComparisonResult = {
  source: "manual_entry";
  evidence_level: "historical_bills";
  confidence: "limited";
  bills: BillResult[];
  covered_days: number;
  gap_days: number;
  baseline_bill_count: number;
  baseline_billing_days: number;
  baseline_us_gallons_per_day: string;
  latest_us_gallons_per_day_change: string;
  latest_percent_change: string | null;
};

const day = (date: string) => Date.parse(`${date}T00:00:00Z`) / 86400000;
const duration = (bill: ManualBill) => day(bill.period_end_exclusive) - day(bill.period_start);
const zero = (amount: string) => /^0+(?:\.0+)?$/.test(amount);
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);

/** Capture validated entries in calendar order; conversion limits remain authoritative on the server. */
export function createBillComparisonEntries(drafts: readonly BillDraft[]): ManualBill[] {
  if (!Array.isArray(drafts) || drafts.length < 2 || drafts.length > 12) {
    throw new Error("Enter between 2 and 12 bills for the same household and meter.");
  }
  const entries = Array.from(drafts, (draft) => createBillEntry(draft))
    .sort((first, second) => first.period_start.localeCompare(second.period_start));
  for (let index = 1; index < entries.length; index++) {
    if (entries[index - 1].period_end_exclusive > entries[index].period_start) {
      throw new Error("Billing periods must not overlap or repeat. Check the dates of each bill.");
    }
  }
  return entries;
}

/** Bind server results to the submitted entries without duplicating Python's decimal calculations. */
export function parseBillComparisonResult(value: unknown, entries: readonly ManualBill[]): BillComparisonResult {
  const invalid = () => new Error("The bill service returned an invalid comparison. Please submit again later.");
  if (!record(value) || entries.length < 2 || entries.length > 12 ||
      value.source !== "manual_entry" || value.evidence_level !== "historical_bills" || value.confidence !== "limited" ||
      typeof value.request_id !== "string" || !/^[0-9a-f-]{36}$/.test(value.request_id) ||
      !Array.isArray(value.bills) || value.bills.length !== entries.length) throw invalid();
  const baselineDays = entries.slice(0, -1).reduce((sum, bill) => sum + duration(bill), 0);
  const coveredDays = baselineDays + duration(entries[entries.length - 1]);
  const gapDays = day(entries[entries.length - 1].period_end_exclusive) - day(entries[0].period_start) - coveredDays;
  if (value.covered_days !== coveredDays || value.gap_days !== gapDays ||
      value.baseline_bill_count !== entries.length - 1 || value.baseline_billing_days !== baselineDays) throw invalid();
  const baseline = value.baseline_us_gallons_per_day;
  const change = value.latest_us_gallons_per_day_change;
  const percent = value.latest_percent_change;
  if (typeof baseline !== "string" || !/^\d{1,7}\.\d{6}$/.test(baseline) || Number(baseline) > 1_000_000 ||
      typeof change !== "string" || !/^-?\d{1,7}\.\d{6}$/.test(change) || Math.abs(Number(change)) > 1_000_000 ||
      change === "-0.000000") throw invalid();
  // An exact positive baseline can round to zero; inspect entered usage rather
  // than the displayed six-decimal baseline when deciding whether % is defined.
  const zeroBaseline = entries.slice(0, -1).every((bill) => zero(bill.usage));
  const percentHundredths = typeof percent === "string" && /^-?\d{1,18}\.\d{2}$/.test(percent)
    ? BigInt(percent.replace(".", "")) : null;
  // The smallest legal positive baseline is 0.000001 L over 366 days.
  // Its maximum possible increase is below 1.4e17 percent. Compare decimal
  // hundredths exactly because this range exceeds Number's integer precision.
  if (zeroBaseline ? percent !== null || baseline !== "0.000000" :
      percentHundredths === null || percentHundredths < BigInt(-10000) ||
      percentHundredths > BigInt("14000000000000000000") || percent === "-0.00") throw invalid();
  let bills: BillResult[];
  try {
    bills = value.bills.map((bill, index) => {
      if (!record(bill)) throw invalid();
      return parseBillResult({ ...bill, request_id: value.request_id }, entries[index]);
    });
  } catch { throw invalid(); }
  return { source: "manual_entry", evidence_level: "historical_bills", confidence: "limited", bills,
    covered_days: coveredDays, gap_days: gapDays, baseline_bill_count: entries.length - 1,
    baseline_billing_days: baselineDays, baseline_us_gallons_per_day: baseline,
    latest_us_gallons_per_day_change: change, latest_percent_change: percent as string | null };
}
