import Link from "next/link";
import { generateHouseholdDataset } from "@/lib/water";
import { DemoWorkspace } from "./demo-workspace";

export default function DemoPage() {
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="mx-auto min-h-screen max-w-[1600px] px-4 py-4 sm:px-6 lg:px-8">
        <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-rule py-3">
          <Link
            href="/"
            className="ui-link gap-3 text-ink"
          >
            <span className="flex size-8 items-center justify-center rounded-lg border border-accent bg-accent-soft text-xs font-bold text-accent">
              A
            </span>

            <div>
              <p className="text-sm font-semibold">AquaMind</p>
              <p className="hidden text-xs text-muted sm:block">
                Demo workspace
              </p>
            </div>
          </Link>

          <div className="flex items-center gap-3">
            <Link href="/analyze" className="ui-link px-2">
              Analyze a bill
            </Link>
            <span className="hidden text-xs text-muted sm:inline-flex">
              Synthetic household
            </span>

            <Link
              href="/"
              className="ui-link px-3"
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
