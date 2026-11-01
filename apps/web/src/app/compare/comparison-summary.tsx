import type { Ref } from "react";
import { BILL_UNITS } from "../../lib/bills";
import type { BillComparisonResult } from "../../lib/bill-comparison";

/** Keep large percentages and entered decimal text out of floating-point formatting. */
export function comparisonNumber(value: string, fixed = false) {
  const [whole, fraction = ""] = value.split(".");
  const decimals = fixed ? fraction : fraction.replace(/0+$/, "");
  const integer = BigInt(whole);
  const sign = whole.startsWith("-") && integer === BigInt(0) ? "-" : "";
  return `${sign}${new Intl.NumberFormat("en-US").format(integer)}${decimals ? `.${decimals}` : ""}`;
}
const dollars = (value: string | null) => {
  if (value === null) return "Unknown";
  const [whole, fraction = ""] = value.split(".");
  return `$${comparisonNumber(`${whole}.${fraction.padEnd(2, "0")}`, true)}`;
};

export function ComparisonSummary({ result, example, headingRef }: {
  result: BillComparisonResult | null; example: boolean; headingRef?: Ref<HTMLHeadingElement>;
}) {
  return <section aria-labelledby="comparison-result-heading" className="min-w-0 border-t border-rule py-8">
    <h2 id="comparison-result-heading" ref={headingRef} tabIndex={-1}
      className="scroll-mt-6 text-2xl font-semibold focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus">
      {result ? "Your bill comparison" : "Compare supplied periods"}
    </h2>
    {result ? <>
      {example && <p className="mt-3 text-sm text-ink-secondary">Example calculation; not your household data.</p>}
      <p className="mt-3 text-sm leading-6 text-ink-secondary">The latest bill is compared with {result.baseline_bill_count} earlier {result.baseline_bill_count === 1 ? "bill" : "bills"} covering {result.baseline_billing_days} days.</p>
      <a href="#comparison-entry-heading" className="ui-link mt-2 underline underline-offset-4">Edit bill details</a>
      <dl className="mt-5 grid gap-x-8 sm:grid-cols-2">
        {[
          ["Earlier daily average (US gallons)", comparisonNumber(result.baseline_us_gallons_per_day)],
          ["Latest daily average (US gallons)", comparisonNumber(result.bills[result.bills.length - 1].us_gallons_per_day)],
          ["Change in US gallons per day", comparisonNumber(result.latest_us_gallons_per_day_change)],
          ["Percentage change", result.latest_percent_change === null ? "Not defined: earlier usage is zero" : `${comparisonNumber(result.latest_percent_change, true)}%`],
        ].map(([label, value]) => <div key={label} className="min-w-0 border-b border-rule py-4">
          <dt className="text-sm text-ink-secondary">{label}</dt>
          <dd className="mt-2 break-words text-2xl font-semibold tabular-nums">{value}</dd>
        </div>)}
      </dl>
      <p className="mt-4 text-sm leading-6 text-ink-secondary">Earlier usage is divided by earlier covered days. The latest bill and gaps are excluded from this baseline.</p>
      {result.gap_days > 0 && <p className="mt-2 text-sm leading-6 text-ink-secondary">{result.gap_days} days between supplied periods are excluded; no usage is assumed for them.</p>}
      {result.baseline_us_gallons_per_day === "0.000000" && result.latest_percent_change !== null &&
        <p className="mt-2 text-sm leading-6 text-ink-secondary">The positive baseline rounds to zero at six decimal places. The percentage uses its unrounded value.</p>}
      <div role="region" aria-label="Billing period results, scroll horizontally if needed" tabIndex={0}
        className="mt-6 max-w-full overflow-x-auto focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus">
        <table className="w-full min-w-xl border-collapse text-left text-sm leading-6">
          <caption className="mb-3 text-left text-ink-secondary">Entered periods, oldest first. End dates are exclusive.</caption>
          <thead><tr className="border-b border-rule">
            {["Billing period", "Entered usage", "US gallons per day", "Water and sewer charges (USD)"].map((label) =>
              <th key={label} scope="col" className="p-3 align-bottom font-medium">{label}</th>)}
          </tr></thead>
          <tbody>{result.bills.map((item, index) => <tr key={item.bill.period_start} className="border-b border-rule">
            <th scope="row" className="p-3 align-top font-medium">
              <span className="block">{item.bill.period_start}</span><span className="block">to {item.bill.period_end_exclusive}</span>
              <span className="block font-normal text-ink-secondary">{item.billing_days} {item.billing_days === 1 ? "day" : "days"}{index === result.bills.length - 1 ? "; latest" : ""}</span>
            </th>
            <td className="p-3 align-top tabular-nums">{item.bill.usage}<span className="block text-ink-secondary">{BILL_UNITS[item.bill.usage_unit]}</span></td>
            <td className="p-3 align-top tabular-nums">{comparisonNumber(item.us_gallons_per_day)}</td>
            <td className="p-3 align-top tabular-nums"><span className="block">Water: {dollars(item.bill.water_charge)}</span>
              <span className="block">Sewer: {dollars(item.bill.sewer_charge)}</span>
              <span className="block">Subtotal: {dollars(item.water_and_sewer_subtotal)}</span></td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="mt-3 text-xs leading-5 text-muted">Subtotals require both entered water and sewer charges. They are not verified invoice totals.</p>
      <p className="mt-5 text-sm leading-6 text-ink-secondary">These entered values are unverified and assumed to describe the same household and meter. Changes in daily averages do not explain occupancy, weather or leaks. No fixture diagnosis, cost trend or savings prediction is inferred.</p>
    </> : <p className="mt-3 text-sm leading-6 text-ink-secondary">Add at least two non-overlapping bills to compare daily averages across different billing lengths. Results appear here after you submit.</p>}
  </section>;
}
