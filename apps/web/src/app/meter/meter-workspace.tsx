"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { BILL_UNITS } from "../../lib/bills";
import { checkMeterFile, MeterClient, MeterError, type MeterOptions, type MeterSummary } from "../../lib/meter-import";

type MeterDraft = Omit<MeterOptions, "volume_unit"> & { volume_unit: MeterOptions["volume_unit"] | "" };
const initial: MeterDraft = { volume_unit: "", interval_minutes: 15, timezone: "", reading_type: "unknown" };
const secondary = "ui-button ui-button-secondary";

export function MeterWorkspace({ client: supplied }: { client?: MeterClient } = {}) {
  const [client] = useState(() => supplied ?? new MeterClient());
  const [options, setOptions] = useState<MeterDraft>(initial);
  const [file, setFile] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [selected, setSelected] = useState<MeterSummary | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState<"importing" | "checking" | "clearing" | null>(null);
  const [error, setError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [notice, setNotice] = useState("");
  const working = useRef(false);
  const mounted = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const alert = useRef<HTMLParagraphElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const focusFileAfterRequest = useRef(false);
  useEffect(() => {
    mounted.current = true;
    const leave = () => {
      client.close(); setSelected(null); setReviewed(false); setConsent(false); setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    };
    window.addEventListener("pagehide", leave);
    return () => { mounted.current = false; window.removeEventListener("pagehide", leave); client.close(); };
  }, [client]);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  useEffect(() => { if (selected) resultHeading.current?.focus({ preventScroll: true }); }, [selected]);
  useEffect(() => {
    if (!busy && focusFileAfterRequest.current) {
      focusFileAfterRequest.current = false;
      fileInput.current?.focus();
    }
  }, [busy, notice]);

  function edit<K extends keyof MeterDraft>(key: K, value: MeterDraft[K]) {
    if (working.current) return;
    setOptions((previous) => ({ ...previous, [key]: value }));
    setConsent(false); setReviewed(false); setError("");
  }
  function resetFile() { setFile(null); if (fileInput.current) fileInput.current.value = ""; }
  function choose(value: File | null) {
    if (working.current) return;
    setError(""); setConsent(false); setReviewed(false); setNotice("");
    try { if (value) checkMeterFile(value); setFile(value); }
    catch (cause) { resetFile(); setError((cause as Error).message); }
  }
  async function run(action: "importing" | "checking" | "clearing") {
    if (working.current) return;
    if (action === "importing" && (!file || !consent || uncertain)) {
      setError(uncertain ? "Check the current selection before importing again." : "Choose a CSV and confirm processing first."); return;
    }
    working.current = true; setBusy(action); setError(""); setNotice(""); setReviewed(false);
    try {
      if (action === "importing") {
        if (!options.volume_unit) throw new MeterError("Choose the volume unit used in your export.");
        const result = await client.importFile(file!, { ...options, volume_unit: options.volume_unit }, consent);
        if (!mounted.current) return;
        setSelected(result); resetFile(); setUncertain(false);
        setNotice("CSV imported. Review the selected period, units and total.");
      } else if (action === "checking") {
        const result = await client.current();
        if (!mounted.current) return;
        setSelected(result); setUncertain(false);
        if (!result) focusFileAfterRequest.current = true;
        setNotice(result ? "Current selection confirmed. Review it before using it." : "No readings are selected in this session.");
      } else {
        await client.clear();
        if (!mounted.current) return;
        setSelected(null); setUncertain(false); resetFile();
        focusFileAfterRequest.current = true;
        setNotice("Selected meter readings cleared.");
      }
    } catch (cause) {
      if (!mounted.current) return;
      const failure = cause instanceof MeterError ? cause : new MeterError("The meter request could not be confirmed. Check the current selection.", true);
      const remainsUncertain = failure.uncertain || (uncertain && !failure.expired);
      if (remainsUncertain || failure.expired) setSelected(null);
      setUncertain(remainsUncertain);
      setError(failure.message);
    } finally {
      working.current = false;
      if (mounted.current) { setBusy(null); setConsent(false); }
    }
  }
  const period = (instant: string) => selected ? new Intl.DateTimeFormat("en-US", {
    timeZone: selected.timezone, dateStyle: "medium", timeStyle: "short",
  }).format(new Date(instant)) : "";

  return <div className="grid items-start gap-8 pb-10 lg:grid-cols-2">
    <section aria-labelledby="meter-import-heading" className="min-w-0">
      <h2 id="meter-import-heading" className="text-xl font-semibold">Import interval CSV</h2>
      <p id="meter-format" className="mt-3 text-sm leading-6 text-ink-secondary">Use exactly <code>interval_start,volume</code> columns. Each row is water used during an interval, not a cumulative meter reading or flow rate. Up to 64 KiB and 672 rows.</p>
      <details className="mt-3 text-sm leading-6 text-ink-secondary">
        <summary className="ui-link cursor-pointer">CSV format and example</summary>
        <pre className="mt-3 overflow-x-auto rounded-lg border border-rule p-3 text-xs" tabIndex={0} aria-label="Fictional CSV format example">{"interval_start,volume\n2026-06-01T00:00:00+00:00,15\n2026-06-01T00:15:00+00:00,12"}</pre>
        <p className="mt-2">Example only. Timestamps need UTC offsets matching your chosen timezone. Rows must be ordered with no gaps or duplicates; the last interval ends one cadence after its timestamp.</p>
      </details>
      <form method="post" autoComplete="off" className="mt-5" aria-busy={!!busy}
        onSubmit={(event) => { event.preventDefault(); void run("importing"); }}>
        <fieldset disabled={!!busy} className="min-w-0 space-y-5">
          <legend className="sr-only">CSV file and interval settings; all fields required</legend>
          <div><label htmlFor="meter-file" className="block text-sm">CSV file (required)</label>
            <input ref={fileInput} id="meter-file" type="file" accept=".csv,text/csv" required aria-describedby="meter-format"
              className="ui-field mt-2 w-full min-w-0" onChange={(event) => choose(event.target.files?.[0] ?? null)} /></div>
          <div className="grid gap-5 sm:grid-cols-2">
            <div><label htmlFor="meter-unit" className="block text-sm">Volume unit (required)</label>
              <select id="meter-unit" required className="ui-field mt-2 w-full" value={options.volume_unit}
                onChange={(event) => edit("volume_unit", event.target.value as MeterOptions["volume_unit"])}>
                <option value="">Choose a unit</option>
                {Object.entries(BILL_UNITS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select></div>
            <div><label htmlFor="meter-cadence" className="block text-sm">Minutes per interval (required)</label>
              <input id="meter-cadence" type="number" min="1" max="60" step="1" required value={Number.isNaN(options.interval_minutes) ? "" : options.interval_minutes}
                className="ui-field mt-2 w-full" onChange={(event) => edit("interval_minutes", event.target.valueAsNumber)} /></div>
          </div>
          <div><label htmlFor="meter-timezone" className="block text-sm">IANA timezone (required)</label>
            <input id="meter-timezone" required maxLength={64} value={options.timezone} placeholder="America/Los_Angeles"
              aria-describedby="meter-timezone-help" className="ui-field mt-2 w-full" onChange={(event) => edit("timezone", event.target.value)} />
            <p id="meter-timezone-help" className="mt-2 text-xs leading-5 text-muted">Use the export’s timezone, such as America/New_York or UTC. It is not inferred from your browser.</p></div>
          <div><label htmlFor="meter-reading" className="block text-sm">Reading type (required)</label>
            <select id="meter-reading" className="ui-field mt-2 w-full" value={options.reading_type}
              onChange={(event) => edit("reading_type", event.target.value as MeterOptions["reading_type"])}>
              <option value="unknown">Not identified</option><option value="actual">Actual</option>
              <option value="estimated">Estimated</option><option value="mixed">Mixed</option>
            </select></div>
          <p id="meter-processing" className="text-sm leading-6 text-ink-secondary">The entire CSV is sent to this server. Include only the two required columns and leave out personal details. Readings stay in temporary session memory for up to one hour; clear them when finished. They are not sent to an external AI service.</p>
          <label className="flex min-h-11 items-start gap-3 text-sm leading-6"><input id="meter-consent" type="checkbox" required checked={consent}
            aria-describedby="meter-processing" className="mt-1 size-4 shrink-0 accent-accent" onChange={(event) => setConsent(event.target.checked)} />Allow the server to process this CSV.</label>
          <button className="ui-button ui-button-primary w-full" disabled={!!busy || uncertain}>
            {busy === "importing" ? "Importing readings…" : selected ? "Import and replace selection" : "Import CSV"}</button>
        </fieldset>
      </form>
      <p role="status" aria-atomic="true" className="mt-3 text-sm leading-6 text-ink-secondary">{busy === "importing" ? "Validating timestamps, units and intervals…" : busy === "checking" ? "Checking the current selection…" : busy === "clearing" ? "Clearing selected readings…" : notice}</p>
      {error && <p ref={alert} tabIndex={-1} role="alert" className="mt-3 rounded-lg border border-warning bg-warning-soft p-3 text-sm leading-6 text-warning focus-visible:outline-2 focus-visible:outline-warning">{error}</p>}
      {uncertain && <div className="mt-3 flex flex-wrap gap-3">
        <button className={secondary} disabled={!!busy} onClick={() => void run("checking")}>Check current selection</button>
        <button className={secondary} disabled={!!busy} onClick={() => void run("clearing")}>Clear server selection</button>
      </div>}
      <p className="mt-4 text-xs leading-5 text-muted">A successful import replaces this session’s previous selection. Closing this workspace attempts to end the session; reloads do not restore uploads.</p>
    </section>
    <section aria-labelledby="meter-result-heading" className="min-w-0 border-t border-rule pt-6 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
      <h2 ref={resultHeading} id="meter-result-heading" tabIndex={-1} className="text-xl font-semibold focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus">Selected meter readings</h2>
      {selected ? <>
        <dl className="mt-5 space-y-4 text-sm">
          <div><dt className="text-ink-secondary">Period in {selected.timezone}</dt><dd className="mt-1 break-words">{period(selected.context.start)} to {period(selected.context.end_exclusive)} (exclusive)</dd></div>
          <div className="flex flex-wrap justify-between gap-2"><dt className="text-ink-secondary">Intervals</dt><dd>{selected.context.reading_count}, every {selected.context.interval_minutes} minutes</dd></div>
          <div className="flex flex-wrap justify-between gap-2"><dt className="text-ink-secondary">Original unit</dt><dd>{BILL_UNITS[selected.context.volume_unit]}</dd></div>
          <div className="flex flex-wrap justify-between gap-2"><dt className="text-ink-secondary">Reading type, reported by you</dt><dd>{selected.context.reading_type === "unknown" ? "Not identified" : selected.context.reading_type}</dd></div>
          <div className="border-y border-rule py-4"><dt className="text-ink-secondary">Total US gallons</dt><dd className="mt-2 break-words text-3xl font-semibold">{new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(Number(selected.total_us_gallons))}</dd></div>
        </dl>
        <label className="mt-5 flex min-h-11 items-start gap-3 text-sm leading-6"><input type="checkbox" id="meter-reviewed" checked={reviewed}
          disabled={!!busy || !!file} className="mt-1 size-4 shrink-0 accent-accent" onChange={(event) => setReviewed(event.target.checked)} />I have checked the selected period, units and total against my export.</label>
        <p className="mt-2 text-sm leading-6 text-ink-secondary">{reviewed ? "Reviewed by you; the readings remain unverified." : file ? "A replacement is pending. Review is available after importing or removing that file." : "Review these readings before using them as evidence."}</p>
        {file && <button className={`${secondary} mt-3`} disabled={!!busy} onClick={() => { resetFile(); setConsent(false); fileInput.current?.focus(); }}>Remove pending file</button>}
        <button className={`${secondary} mt-4`} disabled={!!busy} onClick={() => void run("clearing")}>Clear selected readings</button>
      </> : <p className="mt-3 text-sm leading-6 text-ink-secondary">{uncertain ? "The current selection is unconfirmed. Use the check or clear action to resolve it." : "No readings selected. Import a CSV to review its coverage and total."}</p>}
      <p className="mt-6 border-t border-rule pt-5 text-sm leading-6 text-ink-secondary">User-provided readings remain unverified. No leak score, historical baseline, weather or utility tariff is inferred. Bill evidence and the synthetic demo remain separate.</p>
      <Link href="/analyze" className="ui-link mt-4 underline underline-offset-4">Use a water bill instead</Link>
    </section>
  </div>;
}
