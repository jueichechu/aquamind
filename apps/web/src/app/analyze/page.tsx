import Link from "next/link";
import { BillEntry } from "./bill-entry";

export default async function AnalyzePage({ searchParams }: { searchParams: Promise<{ example?: string }> }) {
  const { example } = await searchParams;
  return <main className="water-desk min-h-screen px-4 py-6 sm:px-6 lg:px-8">
    <div className="mx-auto max-w-5xl">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule pb-5">
        <Link href="/" className="ui-link desk-wordmark text-ink">AquaMind</Link>
        <Link href="/demo" className="ui-link">Explore the synthetic demo</Link>
      </header>
      <div className="max-w-2xl py-8">
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Understand one water bill</h1>
        <p className="mt-4 text-sm leading-6 text-ink-secondary">Enter your billing period and total usage to see US gallons per day. Add water and sewer charges if known. You do not need a smart meter.</p>
      </div>
      <BillEntry initialExample={example === "1"} />
    </div>
  </main>;
}
