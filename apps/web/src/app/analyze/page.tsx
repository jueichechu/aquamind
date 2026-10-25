import Link from "next/link";
import { BillEntry } from "./bill-entry";

export default function AnalyzePage() {
  return <main className="min-h-screen bg-[#07111b] px-4 py-6 text-white sm:px-6 lg:px-8">
    <div className="mx-auto max-w-5xl">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-5">
        <Link href="/" className="rounded text-lg font-semibold focus-visible:outline-2 focus-visible:outline-cyan-300">AquaMind</Link>
        <Link href="/demo" className="rounded text-sm text-cyan-200 hover:text-white focus-visible:outline-2 focus-visible:outline-cyan-300">Explore the synthetic demo →</Link>
      </header>
      <div className="max-w-2xl py-8">
        <p className="text-sm text-cyan-200">Your water data</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Understand one water bill</h1>
        <p className="mt-4 text-sm leading-6 text-slate-300">Enter your billing period and total usage to see US gallons per day. Add water and sewer charges if known. You do not need a smart meter.</p>
      </div>
      <BillEntry />
    </div>
  </main>;
}
