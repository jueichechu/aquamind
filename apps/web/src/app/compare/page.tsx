import Link from "next/link";
import { ComparisonEntry } from "./comparison-entry";

export default function ComparePage() {
  return <main className="water-desk min-h-screen px-4 py-6 sm:px-6 lg:px-8">
    <div className="mx-auto max-w-5xl">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule pb-5">
        <Link href="/" className="ui-link desk-wordmark text-ink">AquaMind</Link>
        <Link href="/analyze" className="ui-link">Analyze one bill</Link>
      </header>
      <div className="max-w-2xl py-8">
        <h1 className="mt-2 break-words text-3xl font-semibold tracking-tight sm:text-4xl">Compare your water bills</h1>
        <p className="mt-4 text-sm leading-6 text-ink-secondary">See how daily usage changed across billing periods.</p>
      </div>
      <ComparisonEntry />
    </div>
  </main>;
}
