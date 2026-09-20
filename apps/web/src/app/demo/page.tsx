import Link from "next/link";

const scenarios = [
  {
    title: "Overnight continuous flow",
    description: "Investigate steady usage detected between 1:15 AM and 6:00 AM.",
    status: "Attention",
  },
  {
    title: "Running toilet pattern",
    description: "Inspect repeated short refill cycles occurring throughout the day.",
    status: "Review",
  },
  {
    title: "Irrigation after rain",
    description: "Compare outdoor watering with recent weather conditions.",
    status: "Opportunity",
  },
];

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
          <aside className="rounded-2xl border border-white/8 bg-white/[0.02] p-4 lg:min-h-[calc(100vh-6.5rem)]">
            <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-slate-600">
              Demo scenarios
            </p>

            <div className="mt-4 space-y-2">
              {scenarios.map((scenario, index) => (
                <button
                  key={scenario.title}
                  type="button"
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    index === 0
                      ? "border-cyan-300/15 bg-cyan-300/[0.06]"
                      : "border-transparent hover:border-white/8 hover:bg-white/[0.025]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-medium text-slate-200">
                      {scenario.title}
                    </p>

                    {index === 0 ? (
                      <span className="mt-1 size-1.5 shrink-0 rounded-full bg-cyan-300" />
                    ) : null}
                  </div>

                  <p className="mt-2 text-xs leading-5 text-slate-600">
                    {scenario.description}
                  </p>
                </button>
              ))}
            </div>

            <div className="mt-8 rounded-xl border border-dashed border-white/10 p-3">
              <p className="text-xs font-medium text-slate-400">
                Data layer next
              </p>
              <p className="mt-1.5 text-xs leading-5 text-slate-600">
                These controls become interactive once the synthetic household
                engine is connected.
              </p>
            </div>
          </aside>

          <section className="min-w-0 space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <SummaryCard label="Today" value="186 gal" detail="-8% vs baseline" />
              <SummaryCard
                label="Current flow"
                value="0.43"
                unit="gal/min"
                detail="Continuous"
              />
              <SummaryCard
                label="Leak risk"
                value="Elevated"
                detail="Since 1:15 AM"
              />
            </div>

            <div className="rounded-2xl border border-white/8 bg-white/[0.02] p-5 sm:p-6">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-slate-200">
                    Household water usage
                  </p>
                  <p className="mt-1 text-xs text-slate-600">
                    15-minute interval preview · synthetic data
                  </p>
                </div>

                <span className="w-fit rounded-full border border-amber-300/10 bg-amber-300/[0.06] px-3 py-1 text-xs text-amber-200">
                  Anomaly window
                </span>
              </div>

              <PlaceholderChart />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <InfoPanel
                eyebrow="Detected pattern"
                title="Continuous overnight flow"
                body="Usage does not return to the expected nighttime baseline. The next phase will calculate this from generated interval data."
              />

              <InfoPanel
                eyebrow="Context"
                title="No recent rainfall context yet"
                body="Weather, utility rates, and fixture context will be added through tools rather than hardcoded into the interface."
              />
            </div>
          </section>

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

function SummaryCard({
  label,
  value,
  unit,
  detail,
}: {
  label: string;
  value: string;
  unit?: string;
  detail: string;
}) {
  return (
    <article className="rounded-2xl border border-white/8 bg-white/[0.02] p-4">
      <p className="text-xs text-slate-600">{label}</p>

      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-2xl font-semibold tracking-tight text-white">
          {value}
        </span>

        {unit ? <span className="text-xs text-slate-600">{unit}</span> : null}
      </div>

      <p className="mt-2 text-xs text-slate-500">{detail}</p>
    </article>
  );
}

function PlaceholderChart() {
  const values = [
    18, 16, 15, 14, 14, 15, 14, 15, 15, 16, 15, 17, 36, 52, 68, 58, 43, 35,
    31, 28, 24, 21, 19, 18, 17, 16, 16, 17, 16, 16, 17, 17,
  ];

  return (
    <div className="mt-7">
      <div className="flex h-64 items-end gap-1 rounded-xl border border-white/8 bg-[#07111b] p-4">
        {values.map((value, index) => (
          <div
            key={`${value}-${index}`}
            className={`min-w-0 flex-1 rounded-sm ${
              index >= 4 && index <= 11
                ? "bg-amber-300/55"
                : "bg-cyan-300/55"
            }`}
            style={{ height: `${value + 14}%` }}
          />
        ))}
      </div>

      <div className="mt-2 flex justify-between text-[10px] text-slate-700">
        <span>12 AM</span>
        <span>6 AM</span>
        <span>12 PM</span>
        <span>6 PM</span>
        <span>Now</span>
      </div>
    </div>
  );
}

function InfoPanel({
  eyebrow,
  title,
  body,
}: {
  eyebrow: string;
  title: string;
  body: string;
}) {
  return (
    <article className="rounded-2xl border border-white/8 bg-white/[0.02] p-5">
      <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-slate-600">
        {eyebrow}
      </p>

      <h2 className="mt-3 text-sm font-medium text-slate-200">{title}</h2>

      <p className="mt-2 text-sm leading-6 text-slate-600">{body}</p>
    </article>
  );
}