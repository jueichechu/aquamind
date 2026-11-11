"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { checkReportSize, REPORT_ACCEPT, type ImportedBill } from "@/lib/bill-import";
import type { DemoClient } from "@/app/demo/demo-client";
import { useBillReadiness } from "./use-bill-readiness";

export function ReportImport({ client, onImported, onSelectionChange, locked = false }: {
  client: DemoClient; onImported: (result: ImportedBill) => void; onSelectionChange: () => void; locked?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const errorBox = useRef<HTMLParagraphElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [share, setShare] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const readiness = useBillReadiness();
  const loading = busy || readiness.status === "starting";
  const statusTitle = readiness.status === "starting" ? "Starting bill analysis…"
    : readiness.status === "unavailable" ? "Bill analysis could not start."
    : busy ? "Reading your report…" : error ? "" : "Ready to read your bill.";
  const statusDetail = readiness.status === "starting"
    ? busy ? "Your report has not been sent yet. Keep this page open."
      : "This may take a minute. You can choose your report while you wait."
    : readiness.status === "unavailable" ? "Your report has not been sent."
    : busy ? "Keep this page open. You’ll review the details before calculating." : "";
  const working = useRef(false);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (error) errorBox.current?.focus(); }, [error]);
  function choose(value: File | null) {
    if (working.current || locked) return;
    onSelectionChange();
    setShare(false); setError(""); setFile(null);
    if (value) {
      try { checkReportSize(value); setFile(value); }
      catch (cause) { setError((cause as Error).message); }
    }
  }
  async function extract() {
    if (working.current || locked || !file || !share || readiness.status !== "ready") return;
    working.current = true; setBusy(true); setError("");
    let sent = false;
    try {
      // A tab may have been idle since its initial check. Recheck before any
      // session creation or report transmission; never repeat paid extraction.
      await readiness.check();
      if (!mounted.current) return;
      sent = true;
      const result = await client.importBill(file, share);
      if (!mounted.current) return;
      setFile(null); setShare(false);
      if (input.current) input.current.value = "";
      onImported(result);
    } catch (cause) {
      if (!mounted.current) return;
      setError(cause instanceof Error ? cause.message : "The report could not be read. Enter its values manually.");
      if (sent) setShare(false);
    } finally { working.current = false; setBusy(false); }
  }
  return <div className="report-intake">
    <Image src="/icons/file.svg" width={44} height={54} alt="" aria-hidden="true" className="report-file-icon" />
    <h2>Add your water bill</h2><p className="report-format">PDF or photo</p>
    <input ref={input} type="file" accept={REPORT_ACCEPT} aria-label="Choose a water bill report"
      className="sr-only" tabIndex={-1} disabled={busy || locked}
      onChange={(event) => choose(event.target.files?.[0] ?? null)} />
    {!file ? <button type="button" className="desk-primary report-choose" disabled={locked} onClick={() => input.current?.click()}>Choose a report</button> :
      <form onSubmit={(event) => { event.preventDefault(); void extract(); }} className="report-consent"
        aria-busy={busy} aria-describedby={loading ? "report-progress-detail" : undefined}>
        <p className="report-filename">{file.name}</p>
        <p id="report-sharing" className="report-disclosure">An external AI service reads your report. Remove personal details first. <a href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noopener noreferrer">Data policy</a></p>
        <label className="report-share-label"><input type="checkbox" checked={share} disabled={busy} required aria-describedby="report-sharing"
          onChange={(event) => setShare(event.target.checked)} />Allow AI to read this report.</label>
        <button className="desk-primary" disabled={!share || busy || readiness.status !== "ready"} aria-busy={busy || readiness.status === "starting"}>
          {readiness.status === "starting" ? "Starting bill analysis…" : busy ? "Reading your report…" : "Read report"}</button>
        <button type="button" className="desk-text-button" disabled={busy} onClick={() => { choose(null); if (input.current) input.current.value = ""; }}>Remove report</button>
      </form>}
    <div className={`report-feedback${loading ? " report-feedback-loading" : ""}`}>
      <p role="status" aria-atomic="true" className="report-status">
        <span id="report-progress-title" className={loading ? "report-status-title" : undefined}>{statusTitle}</span>
        <span id="report-progress-detail" className="report-status-detail">{statusDetail}</span>
      </p>
      {loading && <div role="progressbar" aria-labelledby="report-progress-title"
        aria-describedby="report-progress-detail" className="report-progress">
        <span aria-hidden="true" />
      </div>}
    </div>
    {readiness.status === "unavailable" && <button type="button" className="desk-text-button" disabled={busy || locked}
      onClick={() => { setError(""); void readiness.check().catch(() => {}); }}>Try again</button>}
    {error && <p ref={errorBox} tabIndex={-1} role="alert" className="desk-error">{error}</p>}
    {!busy && <Link href="/analyze" className="desk-underlined report-manual">Enter details instead</Link>}
    {file && <p className="report-format">PDF, PNG, JPEG or WebP. Up to 4 MiB.</p>}
  </div>;
}
