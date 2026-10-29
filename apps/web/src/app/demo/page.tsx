import Link from "next/link";
import { generateHouseholdDataset } from "@/lib/water";
import { DemoWorkspace } from "./demo-workspace";

export default function DemoPage() {
  return (
    <main className="water-desk min-h-screen">
      <div className="mx-auto min-h-screen max-w-[1376px] px-4 py-4 sm:px-6 lg:px-8">
        <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-rule py-3">
          <div>
            <Link href="/" className="ui-link desk-wordmark text-ink">AquaMind</Link>
            <h1 className="text-sm text-muted">Synthetic meter demo</h1>
          </div>

          <div className="flex items-center gap-3">
            <Link href="/analyze" className="ui-link px-2">
              Analyze a bill
            </Link>
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
