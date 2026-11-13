import Link from "next/link";
import { MeterWorkspace } from "./meter-workspace";

export default function MeterPage() {
  return <main className="water-desk min-h-screen px-4 py-6 sm:px-6 lg:px-8">
    <div className="mx-auto max-w-5xl">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule pb-5">
        <Link href="/" className="ui-link desk-wordmark text-ink">AquaMind</Link>
        <nav aria-label="Meter navigation" className="flex flex-wrap items-center gap-4">
          <Link href="/analyze" className="ui-link">Understand a bill</Link>
          <Link href="/demo" className="ui-link">Synthetic demo</Link>
        </nav>
      </header>
      <div className="max-w-2xl py-8">
        <h1 className="min-w-0 break-words text-3xl font-semibold tracking-tight sm:text-4xl">Review your meter readings</h1>
        <p className="mt-4 leading-7 text-ink-secondary">Import interval volumes from a CSV. Check the period, units and total before using them as household evidence.</p>
      </div>
      <MeterWorkspace />
    </div>
  </main>;
}
