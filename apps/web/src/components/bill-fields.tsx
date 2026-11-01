import type { ReactNode } from "react";
import { BILL_UNITS, type BillDraft } from "../lib/bills";

/** Shared bill inputs; the owning form controls submission, busy state and import review. */
export function BillFields({ draft, onChange, idPrefix = "bill",
  descriptionIds = (_field, help) => help, sourceHint = () => null }: {
  draft: BillDraft;
  onChange: (field: keyof BillDraft, value: string) => void;
  idPrefix?: string;
  descriptionIds?: (field: keyof BillDraft, help?: string) => string | undefined;
  sourceHint?: (field: keyof BillDraft, required?: boolean) => ReactNode;
}) {
  const inputStyle = "ui-field mt-2";
  return <>
  <div className="grid gap-4 sm:grid-cols-2">
    <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor={`${idPrefix}-start`}>Period start
      <input id={`${idPrefix}-start`} name="period_start" type="date" required min="0001-01-01" max="9999-12-31"
        value={draft.period_start} onChange={(event) => onChange("period_start", event.target.value)} className={inputStyle} aria-describedby={descriptionIds("period_start")} />
    </label>{sourceHint("period_start", true)}</div>
    <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor={`${idPrefix}-end`}>Period end (exclusive)
      <input id={`${idPrefix}-end`} name="period_end_exclusive" type="date" required min="0001-01-01" max="9999-12-31" aria-describedby={descriptionIds("period_end_exclusive", `${idPrefix}-end-help`)}
        value={draft.period_end_exclusive} onChange={(event) => onChange("period_end_exclusive", event.target.value)} className={inputStyle} />
    </label>{sourceHint("period_end_exclusive", true)}</div>
  </div>
  <p id={`${idPrefix}-end-help`} className="text-xs leading-5 text-muted">Use the first day after the billed period. For a June 1–30 bill, enter June 1 and July 1. Periods must cover 1–366 days.</p>
  <div className="grid gap-4 sm:grid-cols-2">
    <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor={`${idPrefix}-usage`}>Total water usage
      <input id={`${idPrefix}-usage`} name="usage" type="text" inputMode="decimal" required maxLength={16} placeholder="e.g. 8.5" aria-describedby={descriptionIds("usage", `${idPrefix}-usage-help`)}
        value={draft.usage} onChange={(event) => onChange("usage", event.target.value)} className={inputStyle} />
    </label>{sourceHint("usage", true)}</div>
    <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor={`${idPrefix}-unit`}>Usage unit
      <select id={`${idPrefix}-unit`} name="usage_unit" required value={draft.usage_unit} aria-describedby={descriptionIds("usage_unit")}
        onChange={(event) => onChange("usage_unit", event.target.value)} className={inputStyle}>
        <option value="">Select the printed unit</option>
        {Object.entries(BILL_UNITS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>{sourceHint("usage_unit", true)}</div>
  </div>
  <p id={`${idPrefix}-usage-help`} className="text-xs leading-5 text-muted">Enter the usage amount, without commas or unit suffixes. Choose US liquid gallons only if the bill uses US gallons. The limit after conversion is 1,000,000 US gallons.</p>
  <div className="border-t border-rule pt-5">
    <h3 className="font-medium">Charges (optional)</h3>
    <p className="mt-2 text-xs leading-5 text-muted">Leave missing charges blank. Enter 0 only when the bill explicitly shows zero. Only USD charges are supported; usage analysis works without charges.</p>
    <div className="mt-4 grid gap-4 sm:grid-cols-2">
      <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor={`${idPrefix}-water-charge`}>Water charge
        <input id={`${idPrefix}-water-charge`} name="water_charge" type="text" inputMode="decimal" maxLength={13} placeholder="Unknown" aria-describedby={descriptionIds("water_charge")}
          value={draft.water_charge} onChange={(event) => onChange("water_charge", event.target.value)} className={inputStyle} />
      </label>{sourceHint("water_charge")}</div>
      <div className="min-w-0"><label className="block text-sm text-ink-secondary" htmlFor={`${idPrefix}-sewer-charge`}>Sewer charge
        <input id={`${idPrefix}-sewer-charge`} name="sewer_charge" type="text" inputMode="decimal" maxLength={13} placeholder="Unknown" aria-describedby={descriptionIds("sewer_charge")}
          value={draft.sewer_charge} onChange={(event) => onChange("sewer_charge", event.target.value)} className={inputStyle} />
      </label>{sourceHint("sewer_charge")}</div>
    </div>
    <label className="mt-4 block text-sm text-ink-secondary" htmlFor={`${idPrefix}-currency`}>Charge currency
      <select id={`${idPrefix}-currency`} name="currency" value={draft.currency} required={!!(draft.water_charge.trim() || draft.sewer_charge.trim())} aria-describedby={descriptionIds("currency")}
        onChange={(event) => onChange("currency", event.target.value)} className={inputStyle}>
        <option value="">Select if entering charges</option>
        <option value="USD">USD — US dollars</option>
      </select>
    </label>
    {sourceHint("currency", !!(draft.water_charge.trim() || draft.sewer_charge.trim()))}
  </div>
  </>;
}
