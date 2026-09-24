import Link from "next/link";
import { generateHouseholdDataset } from "@/lib/water";
import { HouseholdDashboard } from "./household-dashboard";

export default function DemoPage() {
  return (
    <main className="min-h-screen bg-[#07111b] text-white">
      <div className="mx-auto min-h-screen max-w-[1600px] px-4 py-4 sm:px-6 lg:px-8">
        <header className="flex h-16 items-center justify-between rounded-2xl border border-white/8 bg-white/[0.02] px-4 sm:px-5">
          <Link
            href="/"
            className="flex items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
          >
            <span className="flex size-8 items-center justify-center rounded-lg border border-cyan-300/15 bg-cyan-300/10 text-xs font-bold text-cyan-200">
              A
            </span>

            <div>
              <p className="text-sm font-semibold">AquaMind</p>
              <p className="hidden text-[10px] text-slate-600 sm:block">
                Demo workspace
              </p>
            </div>
          </Link>

          <div className="flex items-center gap-3">
            <span className="hidden rounded-full border border-white/8 px-3 py-1 text-xs text-slate-500 sm:inline-flex">
              Synthetic household
            </span>

            <Link
              href="/"
              className="rounded-lg px-3 py-2 text-sm text-slate-400 transition hover:text-white"
            >
              Exit demo
            </Link>
          </div>
        </header>

        <div className="grid gap-4 py-4 lg:grid-cols-[240px_minmax(0,1fr)_360px]">
          <HouseholdDashboard dataset={generateHouseholdDataset("overnight-leak")} />

          <aside className="flex min-h-[540px] flex-col rounded-2xl border border-white/8 bg-[#0a1521] lg:min-h-[calc(100vh-6.5rem)]">
            <div className="border-b border-white/8 px-5 py-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">AquaMind assistant</p>
                  <p className="mt-0.5 text-xs text-slate-600">
                    Agent integration coming later
                  </p>
                </div>

                <span className="size-2 rounded-full bg-slate-700" />
              </div>
            </div>

            <div className="flex flex-1 items-center justify-center p-6">
              <div className="max-w-xs text-center">
                <div className="mx-auto flex size-11 items-center justify-center rounded-2xl border border-cyan-300/10 bg-cyan-300/[0.05] text-xs font-semibold text-cyan-200">
                  AI
                </div>

                <h2 className="mt-5 text-base font-medium text-slate-200">
                  No simulated chatbot
                </h2>

                <p className="mt-2 text-sm leading-6 text-slate-600">
                  We will connect this panel only after the meter data, API, MCP
                  tools, and agent pathways actually exist.
                </p>
              </div>
            </div>

            <div className="border-t border-white/8 p-4">
              <div className="flex items-center gap-2 rounded-xl border border-white/8 bg-white/[0.025] px-3 py-3">
                <span className="flex-1 text-sm text-slate-700">
                  Ask AquaMind about this household...
                </span>

                <button
                  type="button"
                  disabled
                  className="rounded-lg bg-white/5 px-3 py-1.5 text-xs text-slate-600"
                >
                  Send
                </button>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </main>
  );
}
