"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { checkReportSize, REPORT_ACCEPT, type ImportedBill } from "@/lib/bill-import";
import type { DemoClient } from "@/app/demo/demo-client";

export function ReportImport({ client, onImported, onSelectionChange, locked = false }: {
  client: DemoClient; onImported: (result: ImportedBill) => void; onSelectionChange: () => void; locked?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const errorBox = useRef<HTMLParagraphElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [share, setShare] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const working = useRef(false);
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
    if (working.current || locked || !file || !share) return;
    working.current = true; setBusy(true); setError("");
    try {
      const result = await client.importBill(file, share);
      setFile(null); setShare(false);
      if (input.current) input.current.value = "";
      onImported(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The report could not be read. Enter its values manually.");
      setShare(false);
    } finally { working.current = false; setBusy(false); }
  }
  return <div className="report-intake">
    <Image src="/icons/file.svg" width={44} height={54} alt="" aria-hidden="true" className="report-file-icon" />
    <h2>Add your water bill</h2><p className="report-format">PDF or photo</p>
    <input ref={input} type="file" accept={REPORT_ACCEPT} aria-label="Choose a water bill report"
      className="sr-only" tabIndex={-1} disabled={busy || locked}
      onChange={(event) => choose(event.target.files?.[0] ?? null)} />
    {!file ? <button type="button" className="desk-primary report-choose" disabled={locked} onClick={() => input.current?.click()}>Choose a report</button> :
      <form onSubmit={(event) => { event.preventDefault(); void extract(); }} className="report-consent">
        <p className="report-filename">{file.name}</p>
        <p id="report-sharing" className="report-disclosure">An external AI service reads your report. Remove personal details first. <a href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noopener noreferrer">Data policy</a></p>
        <label className="report-share-label"><input type="checkbox" checked={share} disabled={busy} required aria-describedby="report-sharing"
          onChange={(event) => setShare(event.target.checked)} />Allow AI to read this report.</label>
        <button className="desk-primary" disabled={!share || busy} aria-busy={busy}>{busy ? "Reading your report…" : "Read report"}</button>
        <button type="button" className="desk-text-button" disabled={busy} onClick={() => { choose(null); if (input.current) input.current.value = ""; }}>Remove report</button>
      </form>}
    {busy && <p role="status" className="report-status">Reading once. You&apos;ll review the fields before calculating.</p>}
    {error && <p ref={errorBox} tabIndex={-1} role="alert" className="desk-error">{error}</p>}
    {!busy && <Link href="/analyze" className="desk-underlined report-manual">Enter details instead</Link>}
    {file && <p className="report-format">PDF, PNG, JPEG or WebP. Up to 4 MiB.</p>}
  </div>;
}
