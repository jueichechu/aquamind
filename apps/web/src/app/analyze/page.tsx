import Link from "next/link";
import { Suspense } from "react";
import { BillEntry } from "./bill-entry";
import { QueryBillEntry } from "./query-bill-entry";

export default function AnalyzePage() {
  return <main className="water-desk min-h-screen px-4 py-6 sm:px-6 lg:px-8">
    <div className="mx-auto max-w-5xl">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule pb-5">
        <Link href="/" className="ui-link desk-wordmark text-ink">AquaMind</Link>
        <nav aria-label="Analysis navigation" className="flex flex-wrap items-center gap-4">
          <Link href="/meter" className="ui-link">Meter readings</Link>
          <Link href="/compare" className="ui-link">Compare bills</Link>
          <Link href="/demo" className="ui-link">Explore the synthetic demo</Link>
        </nav>
      </header>
      <div className="max-w-2xl py-8">
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Understand one water bill</h1>
        <p className="mt-4 text-sm leading-6 text-ink-secondary">Enter your billing period and total usage to see US gallons per day. Add water and sewer charges if known. You do not need a smart meter.</p>
      </div>
      <Suspense fallback={<BillEntry />}><QueryBillEntry /></Suspense>
    </div>
  </main>;
}
