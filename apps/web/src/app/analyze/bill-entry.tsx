"use client";

import { useEffect, useRef, useState } from "react";
import { BILL_UNITS, type BillDraft, type BillResult } from "@/lib/bills";
import { DemoClient } from "../demo/demo-client";
import { BillAssistant } from "./bill-assistant";

const empty: BillDraft = { period_start: "", period_end_exclusive: "", usage: "", usage_unit: "",
  water_charge: "", sewer_charge: "", currency: "" };
const example: BillDraft = { period_start: "2026-06-01", period_end_exclusive: "2026-07-01", usage: "8.5", usage_unit: "ccf",
  water_charge: "45.12", sewer_charge: "", currency: "USD" };
const inputStyle = "mt-2 w-full min-w-0 rounded-lg border border-white/20 bg-[#07111b] px-3 py-2.5 text-base text-white focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-60";
const secondary = "rounded-lg border border-white/20 px-3 py-2 text-sm text-slate-200 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-50";
const gallons = (value: string) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(Number(value));
const money = (value: string | null) => value === null ? "Unknown" :
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value));

export function BillEntry() {
  // A separate mounted client keeps this entry independent of the synthetic demo's session.
  const [client] = useState(() => new DemoClient());
  const [draft, setDraft] = useState<BillDraft>({ ...empty });
  const [isExample, setIsExample] = useState(false);
  const [result, setResult] = useState<{ value: BillResult; example: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const working = useRef(false);
  const errorBox = useRef<HTMLParagraphElement>(null);

  useEffect(() => { if (error) errorBox.current?.focus(); }, [error]);

  function edit(key: keyof BillDraft, value: string) {
    if (working.current) return;
    setDraft((previous) => ({ ...previous, [key]: value }));
    setResult(null); setError("");
  }
  function assistantBusy(value: boolean) { working.current = value; setAsking(value); }
  function replace(values: BillDraft, exampleEntry: boolean) {
    if (working.current) return;
    setDraft({ ...values }); setIsExample(exampleEntry); setResult(null); setError("");
  }
  async function submit() {
    if (working.current) return;
    working.current = true; setBusy(true); setError(""); setResult(null);
    const submittedExample = isExample;
    try { setResult({ value: await client.normalizeBill(draft), example: submittedExample }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Your bill could not be analyzed. Please try again later."); }
    finally { working.current = false; setBusy(false); }
  }

  return <div className="grid items-start gap-5 pb-8 lg:grid-cols-2">
    <section aria-labelledby="bill-entry-heading" className="min-w-0 rounded-2xl border border-white/10 bg-[#0a1521] p-5 sm:p-6">
      <h2 id="bill-entry-heading" className="text-lg font-semibold">Enter your bill</h2>
      <p className="mt-2 text-sm leading-6 text-slate-300">Only these fields go to AquaMind for this calculation. They go to OpenAI only if you separately choose to ask about the calculated bill. There is no saved bill history. Leave out your name, address and account number.</p>
      <form method="post" autoComplete="off" className="mt-5" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <fieldset disabled={busy || asking} className="min-w-0 space-y-5">
          <legend className="sr-only">Billing dates, usage and optional charges</legend>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={secondary} onClick={() => replace(example, true)}>Use an example bill</button>
            <button type="button" className={secondary} onClick={() => replace(empty, false)}>Clear bill</button>
          </div>
          {isExample && <p className="text-sm text-cyan-200">Example values · not your household data. Clear the form to enter your own bill.</p>}
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="min-w-0 text-sm text-slate-200" htmlFor="bill-start">Period start
              <input id="bill-start" name="period_start" type="date" required min="0001-01-01" max="9999-12-31"
                value={draft.period_start} onChange={(event) => edit("period_start", event.target.value)} className={inputStyle} />
            </label>
            <label className="min-w-0 text-sm text-slate-200" htmlFor="bill-end">Period end (exclusive)
              <input id="bill-end" name="period_end_exclusive" type="date" required min="0001-01-01" max="9999-12-31" aria-describedby="bill-end-help"
                value={draft.period_end_exclusive} onChange={(event) => edit("period_end_exclusive", event.target.value)} className={inputStyle} />
            </label>
          </div>
          <p id="bill-end-help" className="text-xs leading-5 text-slate-400">Use the first day after the billed period. For a June 1–30 bill, enter June 1 and July 1. Periods must cover 1–366 days.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="min-w-0 text-sm text-slate-200" htmlFor="bill-usage">Total water usage
              <input id="bill-usage" name="usage" type="text" inputMode="decimal" required maxLength={16} placeholder="e.g. 8.5" aria-describedby="bill-usage-help"
                value={draft.usage} onChange={(event) => edit("usage", event.target.value)} className={inputStyle} />
            </label>
            <label className="min-w-0 text-sm text-slate-200" htmlFor="bill-unit">Usage unit
              <select id="bill-unit" name="usage_unit" required value={draft.usage_unit}
                onChange={(event) => edit("usage_unit", event.target.value)} className={inputStyle}>
                <option value="">Select the printed unit</option>
                {Object.entries(BILL_UNITS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          </div>
          <p id="bill-usage-help" className="text-xs leading-5 text-slate-400">Enter the usage amount, without commas or unit suffixes. Choose US liquid gallons only if the bill uses US gallons. The limit after conversion is 1,000,000 US gallons.</p>
          <div className="border-t border-white/10 pt-5">
            <h3 className="font-medium">Charges (optional)</h3>
            <p className="mt-2 text-xs leading-5 text-slate-400">Leave missing charges blank. Enter 0 only when the bill explicitly shows zero. Only USD charges are supported; usage analysis works without charges.</p>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="min-w-0 text-sm text-slate-200" htmlFor="bill-water-charge">Water charge
                <input id="bill-water-charge" name="water_charge" type="text" inputMode="decimal" maxLength={13} placeholder="Unknown"
                  value={draft.water_charge} onChange={(event) => edit("water_charge", event.target.value)} className={inputStyle} />
              </label>
              <label className="min-w-0 text-sm text-slate-200" htmlFor="bill-sewer-charge">Sewer charge
                <input id="bill-sewer-charge" name="sewer_charge" type="text" inputMode="decimal" maxLength={13} placeholder="Unknown"
                  value={draft.sewer_charge} onChange={(event) => edit("sewer_charge", event.target.value)} className={inputStyle} />
              </label>
            </div>
            <label className="mt-4 block text-sm text-slate-200" htmlFor="bill-currency">Charge currency
              <select id="bill-currency" name="currency" value={draft.currency} required={!!(draft.water_charge.trim() || draft.sewer_charge.trim())}
                onChange={(event) => edit("currency", event.target.value)} className={inputStyle}>
                <option value="">Select if entering charges</option>
                <option value="USD">USD — US dollars</option>
              </select>
            </label>
          </div>
          <button className="w-full rounded-lg bg-cyan-300 px-4 py-3 text-sm font-semibold text-slate-950 hover:bg-cyan-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:opacity-50">
            {busy ? "Calculating…" : "Calculate bill usage"}
          </button>
        </fieldset>
      </form>
      <p role="status" className="mt-3 text-sm text-slate-300">{busy ? "Calculating your bill usage…" : result ?
        `Bill calculated: ${result.value.billing_days} days, ${gallons(result.value.us_gallons_per_day)} US gallons per day.` : ""}</p>
      {error && <p ref={errorBox} tabIndex={-1} role="alert" className="mt-3 rounded-lg border border-amber-300/25 bg-amber-300/5 p-3 text-sm leading-6 text-amber-200 focus-visible:outline-2 focus-visible:outline-amber-300">{error}</p>}
      <p className="mt-4 text-xs leading-5 text-slate-400">Use Clear bill to remove your entry. Reloading starts a new calculation; there is no saved bill history or automatic submission.</p>
    </section>

    <section aria-labelledby="bill-result-heading" className="min-w-0 rounded-2xl border border-white/10 bg-[#0a1521] p-5 sm:p-6">
      <p className="text-xs font-medium text-cyan-200">Bill only · Limited evidence</p>
      <h2 id="bill-result-heading" className="mt-2 text-lg font-semibold">{result ? "Your bill breakdown" : "What this bill can tell you"}</h2>
      {result ? <>
        {result.example && <p className="mt-3 text-sm text-cyan-200">Example calculation · not your household data</p>}
        <p className="mt-3 text-sm leading-6 text-slate-300">{result.value.bill.period_start} to {result.value.bill.period_end_exclusive} (exclusive) · {result.value.billing_days} days</p>
        <dl className="mt-5 space-y-4">
          <div className="rounded-xl border border-cyan-300/20 bg-cyan-300/5 p-4">
            <dt className="text-sm text-cyan-100">Average US gallons per day</dt>
            <dd data-testid="bill-daily-usage" className="mt-2 break-words text-3xl font-semibold tracking-tight">{gallons(result.value.us_gallons_per_day)}</dd>
          </div>
          <div className="flex flex-wrap justify-between gap-2 text-sm"><dt className="text-slate-300">Total US gallons</dt><dd className="font-medium">{gallons(result.value.total_us_gallons)}</dd></div>
          <div className="flex flex-wrap justify-between gap-2 text-sm"><dt className="text-slate-300">Entered usage</dt><dd className="font-medium">{result.value.bill.usage} {BILL_UNITS[result.value.bill.usage_unit]}</dd></div>
          <div className="flex flex-wrap justify-between gap-2 border-t border-white/10 pt-4 text-sm"><dt className="text-slate-300">Water charge</dt><dd>{money(result.value.bill.water_charge)}</dd></div>
          <div className="flex flex-wrap justify-between gap-2 text-sm"><dt className="text-slate-300">Sewer charge</dt><dd>{money(result.value.bill.sewer_charge)}</dd></div>
          <div className="flex flex-wrap justify-between gap-2 text-sm"><dt className="text-slate-300">Water + sewer subtotal</dt><dd>{money(result.value.water_and_sewer_subtotal)}</dd></div>
        </dl>
        <p className="mt-3 text-xs leading-5 text-slate-400">The subtotal includes only entered water and sewer charges, not a verified invoice total. Both charges are needed to calculate it.</p>
      </> : <p className="mt-3 text-sm leading-6 text-slate-300">Your calculation will show the billing days, total US gallons and daily average. Known charges stay separate from missing values.</p>}
      <div className="mt-6 border-t border-white/10 pt-5">
        <h3 className="text-sm font-semibold">Evidence and limits</h3>
        <ul className="mt-3 list-disc space-y-3 pl-5 text-sm leading-6 text-slate-300">
          <li>Values are manually entered and unverified; no original bill has been inspected.</li>
          <li>One bill cannot establish a usage trend, precise leak timing or which fixture is responsible.</li>
          <li>No leak score, utility tariff or savings prediction is inferred.</li>
        </ul>
      </div>
      {result && <BillAssistant client={client} bill={result.value.bill} isExample={result.example} onBusyChange={assistantBusy} />}
    </section>
  </div>;
}
