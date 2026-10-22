import Link from "next/link";
import { generateHouseholdDataset } from "@/lib/water";
import { DemoWorkspace } from "./demo-workspace";

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

        <DemoWorkspace initialDataset={generateHouseholdDataset("overnight-leak")} />
      </div>
    </main>
  );
}
