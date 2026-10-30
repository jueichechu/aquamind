"use client";

import { useEffect, useRef, useState } from "react";
import { BILL_UNITS, type BillDraft, type BillResult } from "../../lib/bills";
import { DemoClient } from "../demo/demo-client";
import { BillAssistant } from "./bill-assistant";
import type { BillEvidence } from "../../lib/bill-import";
import { BillReadingNote, BillSourceHint } from "../../components/bill-evidence";

const empty: BillDraft = { period_start: "", period_end_exclusive: "", usage: "", usage_unit: "",
  water_charge: "", sewer_charge: "", currency: "" };
const example: BillDraft = { period_start: "2026-06-01", period_end_exclusive: "2026-07-01", usage: "8.5", usage_unit: "ccf",
  water_charge: "45.12", sewer_charge: "", currency: "USD" };
const inputStyle = "ui-field mt-2";
const secondary = "ui-button ui-button-secondary";
const gallons = (value: string) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(Number(value));
const money = (value: string | null) => value === null ? "Unknown" :
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value));

export function BillEntry({ initialDraft, initialExample = false, imported = false, evidence, client: providedClient, onBusyChange }: {
  initialDraft?: BillDraft; initialExample?: boolean; imported?: boolean; client?: DemoClient; onBusyChange?: (busy: boolean) => void;
  evidence?: BillEvidence;
} = {}) {
  // A separate mounted client keeps this entry independent of the synthetic demo's session.
  const [client] = useState(() => providedClient ?? new DemoClient());
  const [draft, setDraft] = useState<BillDraft>({ ...(initialDraft ?? (initialExample ? example : empty)) });
  const [isExample, setIsExample] = useState(initialExample);
  const [fromImport, setFromImport] = useState(imported);
  const [reviewed, setReviewed] = useState(false);
  const [result, setResult] = useState<{ value: BillResult; example: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const working = useRef(false);
  const errorBox = useRef<HTMLParagraphElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => { if (error) errorBox.current?.focus(); }, [error]);
  useEffect(() => {
    if (result) {
      resultHeading.current?.focus({ preventScroll: true });
      resultHeading.current?.scrollIntoView({ block: "start", behavior: "instant" });
    }
  }, [result]);
  useEffect(() => { onBusyChange?.(busy || asking); return () => onBusyChange?.(false); }, [busy, asking, onBusyChange]);

  function edit(key: keyof BillDraft, value: string) {
    if (working.current) return;
    setDraft((previous) => ({ ...previous, [key]: value }));
    setReviewed(false);
    setResult(null); setError("");
  }
  function assistantBusy(value: boolean) { working.current = value; setAsking(value); }
  function replace(values: BillDraft, exampleEntry: boolean) {
    if (working.current) return;
    setDraft({ ...values }); setIsExample(exampleEntry); setResult(null); setError("");
    setFromImport(false); setReviewed(false);
  }
  async function submit() {
    if (working.current) return;
    if (fromImport && !reviewed) return;
    working.current = true; setBusy(true); setError(""); setResult(null);
    const submittedExample = isExample;
    try { setResult({ value: await client.normalizeBill(draft), example: submittedExample }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Your bill could not be analyzed. Please try again later."); }
    finally { working.current = false; setBusy(false); }
  }

  function descriptionIds(field: keyof BillDraft, help?: string) {
    return [help, fromImport && evidence ? `bill-${field}-source` : undefined].filter(Boolean).join(" ") || undefined;
  }
  function sourceHint(field: keyof BillDraft, required = false) {
    if (!fromImport || !evidence) return null;
    return <BillSourceHint id={`bill-${field}-source`} source={evidence.fields[field]}
      changed={draft[field] !== (initialDraft?.[field] ?? "")} empty={!draft[field].trim()} required={required} reviewed={reviewed} />;
  }

  return <div className="grid items-start gap-5 pb-8 lg:grid-cols-2">
    {fromImport && <div className="border-y border-rule py-4 lg:col-span-2"><BillReadingNote evidence={evidence} /></div>}
    <section aria-labelledby="bill-entry-heading" className="min-w-0 rounded-2xl border border-rule bg-surface p-5 sm:p-6">
      <h2 id="bill-entry-heading" tabIndex={-1} className="scroll-mt-6 text-lg font-semibold focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus">Enter your bill</h2>
      <p className="mt-2 text-sm leading-6 text-ink-secondary">Calculating uses only these fields and does not use AI. There is no saved bill history. Leave out personal details.</p>
      {fromImport && <p className="mt-3 text-sm leading-6 text-ink-secondary">These are AI-extracted candidates. Suggested source pages are unverified. Check every field against your report.</p>}
      <form method="post" autoComplete="off" className="mt-5" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <fieldset disabled={busy || asking} className="min-w-0 space-y-5">
          <legend className="sr-only">Billing dates, usage and optional charges</legend>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={secondary} onClick={() => replace(example, true)}>Use an example bill</button>
            <button type="button" className={secondary} onClick={() => replace(empty, false)}>Clear bill</button>
          </div>
          {isExample && <p className="text-sm text-ink-secondary">Example values; not your household data. Clear the form to enter your own bill.</p>}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor="bill-start">Period start
              <input id="bill-start" name="period_start" type="date" required min="0001-01-01" max="9999-12-31"
                value={draft.period_start} onChange={(event) => edit("period_start", event.target.value)} className={inputStyle} aria-describedby={descriptionIds("period_start")} />
            </label>{sourceHint("period_start", true)}</div>
            <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor="bill-end">Period end (exclusive)
              <input id="bill-end" name="period_end_exclusive" type="date" required min="0001-01-01" max="9999-12-31" aria-describedby={descriptionIds("period_end_exclusive", "bill-end-help")}
                value={draft.period_end_exclusive} onChange={(event) => edit("period_end_exclusive", event.target.value)} className={inputStyle} />
            </label>{sourceHint("period_end_exclusive", true)}</div>
          </div>
          <p id="bill-end-help" className="text-xs leading-5 text-muted">Use the first day after the billed period. For a June 1–30 bill, enter June 1 and July 1. Periods must cover 1–366 days.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor="bill-usage">Total water usage
              <input id="bill-usage" name="usage" type="text" inputMode="decimal" required maxLength={16} placeholder="e.g. 8.5" aria-describedby={descriptionIds("usage", "bill-usage-help")}
                value={draft.usage} onChange={(event) => edit("usage", event.target.value)} className={inputStyle} />
            </label>{sourceHint("usage", true)}</div>
            <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor="bill-unit">Usage unit
              <select id="bill-unit" name="usage_unit" required value={draft.usage_unit} aria-describedby={descriptionIds("usage_unit")}
                onChange={(event) => edit("usage_unit", event.target.value)} className={inputStyle}>
                <option value="">Select the printed unit</option>
                {Object.entries(BILL_UNITS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>{sourceHint("usage_unit", true)}</div>
          </div>
          <p id="bill-usage-help" className="text-xs leading-5 text-muted">Enter the usage amount, without commas or unit suffixes. Choose US liquid gallons only if the bill uses US gallons. The limit after conversion is 1,000,000 US gallons.</p>
          <div className="border-t border-rule pt-5">
            <h3 className="font-medium">Charges (optional)</h3>
            <p className="mt-2 text-xs leading-5 text-muted">Leave missing charges blank. Enter 0 only when the bill explicitly shows zero. Only USD charges are supported; usage analysis works without charges.</p>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor="bill-water-charge">Water charge
                <input id="bill-water-charge" name="water_charge" type="text" inputMode="decimal" maxLength={13} placeholder="Unknown" aria-describedby={descriptionIds("water_charge")}
                  value={draft.water_charge} onChange={(event) => edit("water_charge", event.target.value)} className={inputStyle} />
              </label>{sourceHint("water_charge")}</div>
              <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor="bill-sewer-charge">Sewer charge
                <input id="bill-sewer-charge" name="sewer_charge" type="text" inputMode="decimal" maxLength={13} placeholder="Unknown" aria-describedby={descriptionIds("sewer_charge")}
                  value={draft.sewer_charge} onChange={(event) => edit("sewer_charge", event.target.value)} className={inputStyle} />
              </label>{sourceHint("sewer_charge")}</div>
            </div>
            <label className="mt-4 block text-sm text-ink-secondary" htmlFor="bill-currency">Charge currency
              <select id="bill-currency" name="currency" value={draft.currency} required={!!(draft.water_charge.trim() || draft.sewer_charge.trim())} aria-describedby={descriptionIds("currency")}
                onChange={(event) => edit("currency", event.target.value)} className={inputStyle}>
                <option value="">Select if entering charges</option>
                <option value="USD">USD — US dollars</option>
              </select>
            </label>
            {sourceHint("currency", !!(draft.water_charge.trim() || draft.sewer_charge.trim()))}
          </div>
          {fromImport && <label className="flex items-start gap-3 text-sm leading-6 text-ink-secondary"><input type="checkbox" required checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} className="mt-1 size-4 shrink-0 accent-accent" />I have checked the dates, usage, units and optional charges against my report.</label>}
          <button disabled={fromImport && !reviewed} className="ui-button ui-button-primary w-full">
            {busy ? "Calculating…" : "Calculate bill usage"}
          </button>
        </fieldset>
      </form>
      <p role="status" className="mt-3 text-sm text-ink-secondary">{busy ? "Calculating your bill usage…" : result ?
        `Bill calculated: ${result.value.billing_days} days, ${gallons(result.value.us_gallons_per_day)} US gallons per day.` : ""}</p>
      {error && <p ref={errorBox} tabIndex={-1} role="alert" className="mt-3 rounded-lg border border-warning bg-warning-soft p-3 text-sm leading-6 text-warning focus-visible:outline-2 focus-visible:outline-warning">{error}</p>}
      <p className="mt-4 text-xs leading-5 text-muted">Use Clear bill to remove your entry. Reloading starts a new calculation; there is no saved bill history or automatic submission.</p>
    </section>

    <section aria-labelledby="bill-result-heading" className="min-w-0 rounded-2xl border border-rule bg-surface p-5 sm:p-6">
      <p className="text-xs font-medium text-ink-secondary">Bill only; Limited evidence</p>
      <h2 ref={resultHeading} id="bill-result-heading" tabIndex={-1} className="mt-2 scroll-mt-6 text-lg font-semibold focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus">{result ? "Your bill breakdown" : "What this bill can tell you"}</h2>
      {result ? <>
        {result.example && <p className="mt-3 text-sm text-ink-secondary">Example calculation; not your household data</p>}
        <p className="mt-3 text-sm leading-6 text-ink-secondary">{result.value.bill.period_start} to {result.value.bill.period_end_exclusive} (exclusive); {result.value.billing_days} days</p>
        {fromImport && <div className="mt-3"><BillReadingNote evidence={evidence} /></div>}
        <a href="#bill-entry-heading" className="ui-link mt-2 underline underline-offset-4">Edit bill details</a>
        <dl className="mt-5 space-y-4">
          <div className="rounded-xl border border-rule bg-accent-soft p-4">
            <dt className="text-sm text-ink">Average US gallons per day</dt>
            <dd data-testid="bill-daily-usage" className="mt-2 break-words text-3xl font-semibold tracking-tight">{gallons(result.value.us_gallons_per_day)}</dd>
          </div>
          <div className="flex flex-wrap justify-between gap-2 text-sm"><dt className="text-ink-secondary">Total US gallons</dt><dd className="font-medium">{gallons(result.value.total_us_gallons)}</dd></div>
          <div className="flex flex-wrap justify-between gap-2 text-sm"><dt className="text-ink-secondary">Entered usage</dt><dd className="font-medium">{result.value.bill.usage} {BILL_UNITS[result.value.bill.usage_unit]}</dd></div>
          <div className="flex flex-wrap justify-between gap-2 border-t border-rule pt-4 text-sm"><dt className="text-ink-secondary">Water charge</dt><dd>{money(result.value.bill.water_charge)}</dd></div>
          <div className="flex flex-wrap justify-between gap-2 text-sm"><dt className="text-ink-secondary">Sewer charge</dt><dd>{money(result.value.bill.sewer_charge)}</dd></div>
          <div className="flex flex-wrap justify-between gap-2 text-sm"><dt className="text-ink-secondary">Water + sewer subtotal</dt><dd>{money(result.value.water_and_sewer_subtotal)}</dd></div>
        </dl>
        <p className="mt-3 text-xs leading-5 text-muted">The subtotal includes only entered water and sewer charges, not a verified invoice total. Both charges are needed to calculate it.</p>
      </> : <p className="mt-3 text-sm leading-6 text-ink-secondary">Your calculation will show the billing days, total US gallons and daily average. Known charges stay separate from missing values.</p>}
      <div className="mt-6 border-t border-rule pt-5">
        <h3 className="text-sm font-semibold">Evidence and limits</h3>
        <ul className="mt-3 list-disc space-y-3 pl-5 text-sm leading-6 text-ink-secondary">
          <li>{fromImport ? reviewed ? "Values were extracted with AI and reviewed by you; they remain unverified." : "Values were extracted with AI and need your review; they remain unverified." : "Values are manually entered and unverified; no original bill has been inspected."}</li>
          <li>One bill cannot establish a usage trend, precise leak timing or which fixture is responsible.</li>
          <li>No leak score, utility tariff or savings prediction is inferred.</li>
        </ul>
      </div>
      {result && <BillAssistant client={client} bill={result.value.bill} isExample={result.example} onBusyChange={assistantBusy} />}
    </section>
  </div>;
}
