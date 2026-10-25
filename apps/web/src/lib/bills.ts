export const BILL_UNITS = {
  us_gallons: "US liquid gallons",
  ccf: "CCF (100 cubic feet)",
  cubic_meters: "Cubic meters (m³)",
  liters: "Liters",
} as const;

export type BillDraft = {
  period_start: string;
  period_end_exclusive: string;
  usage: string;
  usage_unit: string;
  water_charge: string;
  sewer_charge: string;
  currency: string;
};
export type ManualBill = {
  period_start: string;
  period_end_exclusive: string;
  usage: string;
  usage_unit: keyof typeof BILL_UNITS;
  water_charge: string | null;
  sewer_charge: string | null;
  currency: "USD" | null;
};
export type BillResult = {
  bill: ManualBill;
  billing_days: number;
  total_us_gallons: string;
  us_gallons_per_day: string;
  water_and_sewer_subtotal: string | null;
};

function calendarDay(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return NaN;
  const instant = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(instant) && new Date(instant).toISOString().slice(0, 10) === value ? instant / 86400000 : NaN;
}
const days = (bill: { period_start: string; period_end_exclusive: string }) =>
  calendarDay(bill.period_end_exclusive) - calendarDay(bill.period_start);
const amount = (value: string, places: number) => new RegExp(`^\\d{1,9}(?:\\.\\d{1,${places}})?$`).test(value);
const canonical = (value: string) => value.replace(/^0+(?=\d)/, "").replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");

/** Validate form syntax; Python remains authoritative for unit conversion and usage limits. */
export function createBillEntry(draft: BillDraft): ManualBill {
  if (["period_start", "period_end_exclusive", "usage", "usage_unit", "water_charge", "sewer_charge", "currency"]
    .some((key) => typeof draft[key as keyof BillDraft] !== "string")) throw new Error("Check the bill fields.");
  const period = days(draft);
  if (!Number.isInteger(period) || period < 1 || period > 366) {
    throw new Error("Enter valid billing dates covering 1–366 days. The end date is the first day after the billed period.");
  }
  if (!Object.hasOwn(BILL_UNITS, draft.usage_unit)) throw new Error("Select the usage unit printed on your bill.");
  const usage = draft.usage.trim();
  if (!amount(usage, 6)) throw new Error("Enter non-negative usage with up to six decimal places, without commas or unit suffixes.");
  const charges = [draft.water_charge.trim(), draft.sewer_charge.trim()];
  if (charges.some((value) => value !== "" && (!amount(value, 2) || Number(value) > 1_000_000))) {
    throw new Error("Enter charges from 0 to 1,000,000 with up to two decimal places, or leave them blank if unknown.");
  }
  if ((draft.currency !== "" && draft.currency !== "USD") || (charges.some(Boolean) && draft.currency !== "USD")) {
    throw new Error("Select USD for entered charges. Only USD charges are supported; leave other-currency charges blank.");
  }
  return { period_start: draft.period_start, period_end_exclusive: draft.period_end_exclusive,
    usage, usage_unit: draft.usage_unit as ManualBill["usage_unit"],
    water_charge: charges[0] || null, sewer_charge: charges[1] || null, currency: draft.currency === "USD" ? "USD" : null };
}

export function parseBillResult(value: unknown, entry: ManualBill): BillResult {
  const invalid = () => new Error("The bill service returned an invalid result. Please submit again later.");
  if (!value || typeof value !== "object") throw invalid();
  const data = value as Record<string, unknown>;
  if (data.source !== "manual_entry" || data.evidence_level !== "bill_only" || data.confidence !== "limited" ||
      typeof data.request_id !== "string" || !/^[0-9a-f-]{36}$/.test(data.request_id) ||
      data.billing_days !== days(entry) || !data.bill || typeof data.bill !== "object") throw invalid();
  const echoed = data.bill as Record<string, unknown>;
  for (const key of ["period_start", "period_end_exclusive", "usage_unit", "currency"] as const) {
    if (echoed[key] !== entry[key]) throw invalid();
  }
  for (const key of ["usage", "water_charge", "sewer_charge"] as const) {
    const actual = echoed[key];
    const expected = entry[key];
    if (expected === null ? actual !== null : typeof actual !== "string" ||
        !amount(actual, key === "usage" ? 6 : 2) || canonical(actual) !== canonical(expected)) throw invalid();
  }
  for (const key of ["total_us_gallons", "us_gallons_per_day"] as const) {
    if (typeof data[key] !== "string" || !/^\d{1,7}\.\d{6}$/.test(data[key]) || Number(data[key]) > 1_000_000) throw invalid();
  }
  const subtotal = data.water_and_sewer_subtotal;
  if (entry.water_charge === null || entry.sewer_charge === null) {
    if (subtotal !== null) throw invalid();
  } else if (typeof subtotal !== "string" || !/^\d{1,7}\.\d{2}$/.test(subtotal) || Number(subtotal) > 2_000_000) throw invalid();
  return { bill: { ...entry }, billing_days: data.billing_days as number,
    total_us_gallons: data.total_us_gallons as string, us_gallons_per_day: data.us_gallons_per_day as string,
    water_and_sewer_subtotal: subtotal as string | null };
}
