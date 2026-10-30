"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { DemoClient } from "@/app/demo/demo-client";
import { BillEntry } from "@/app/analyze/bill-entry";
import { IMPORT_WARNINGS, type ImportedBill } from "@/lib/bill-import";
import { ReportImport } from "./report-import";

export function WaterDesk() {
  const [client] = useState(() => new DemoClient());
  const [analyzing, setAnalyzing] = useState(false);
  const [imported, setImported] = useState<{ result: ImportedBill; version: number } | null>(null);
  const review = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (imported) { review.current?.focus(); review.current?.scrollIntoView({ block: "start" }); }
  }, [imported]);
  return <main className="water-desk">
    <header className="desk-header desk-container">
      <Link href="/" className="desk-wordmark">AquaMind</Link>
      <nav aria-label="Main navigation"><a href="#how-it-works">How it works</a><a href="#water-guide">Water guide</a></nav>
    </header>
    <section className="desk-hero desk-container" aria-labelledby="desk-heading">
      <div className="desk-introduction">
        <h1 id="desk-heading">Your water bill,<br className="desk-heading-break" /> made clearer.</h1>
        <p className="desk-lead">Understand what your household uses and where to start.</p>
        <ReportImport client={client} locked={analyzing} onSelectionChange={() => setImported(null)}
          onImported={(result) => setImported((previous) => ({ result, version: (previous?.version ?? 0) + 1 }))} />
        <Link href="/analyze?example=1" className="desk-underlined desk-example-link">Explore an example</Link>
      </div>
      <aside className="example-report" aria-labelledby="example-report-heading">
        <h2 id="example-report-heading">Example report</h2>
        <div className="example-calculation">
          <dl className="example-report-facts"><div><dt>Water used</dt><dd>8.5 CCF</dd></div><div><dt>Billing period</dt><dd>30 days</dd></div></dl>
          <div className="example-conversion" aria-hidden="true" />
        </div>
        <p className="example-daily"><span>212</span>US gallons per day</p>
        <p className="example-average">Household daily average</p>
        <p className="example-method">Total water used divided by billing days.</p>
      </aside>
    </section>
    {imported && <section className="desk-review desk-container" aria-labelledby="review-heading">
      <h2 ref={review} tabIndex={-1} id="review-heading" className="focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus">Review your report</h2>
      <p className="desk-review-intro">Check every value against the original, including dates and units. Fill in anything missing before calculating.</p>
      {!!imported.result.warnings.length && <ul className="desk-import-warnings">{imported.result.warnings.map((warning) => <li key={warning}>{IMPORT_WARNINGS[warning]}</li>)}</ul>}
      <BillEntry key={imported.version} initialDraft={imported.result.draft} evidence={imported.result.evidence} imported client={client} onBusyChange={setAnalyzing} />
    </section>}
    <section id="how-it-works" className="desk-how"><div className="desk-container desk-how-grid">
      <h2>Read the numbers.<br />Choose your next step.</h2>
      <ol><li>Review the values from your report</li><li>See usage in everyday units</li><li>Ask a question when you need context</li></ol>
    </div></section>
    <section id="water-guide" className="desk-guide desk-container" aria-labelledby="water-guide-heading">
      <h2 id="water-guide-heading">A clearer picture starts with one bill.</h2>
      <div><p>A daily average makes billing periods easier to compare. CCF means 100 cubic feet of water; your bill may use gallons, liters or cubic meters instead.</p>
        <p>One bill cannot confirm a leak or identify a fixture. Keep earlier bills and check your meter when you need more evidence.</p>
        <Link href="/demo" className="desk-underlined">Explore the synthetic meter demo</Link></div>
    </section>
    <footer className="desk-footer desk-container"><Link href="/" className="desk-wordmark">AquaMind</Link><p>A little clarity for your home&apos;s water.</p></footer>
  </main>;
}
