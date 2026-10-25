import Link from "next/link";

const capabilities = [
  {
    number: "01",
    title: "Meter intelligence",
    description:
      "Investigate household water consumption patterns and surface unusual usage.",
  },
  {
    number: "02",
    title: "Multimodal diagnosis",
    description:
      "Combine meter readings with text, voice, fixture images, weather, and utility context.",
  },
  {
    number: "03",
    title: "Actionable conservation",
    description:
      "Translate evidence into practical recommendations with transparent assumptions.",
  },
];

const signals = [
  "Water meter",
  "Weather",
  "Images",
  "Voice",
  "Utility context",
];

export default function Home() {
  return (
    <main className="min-h-screen overflow-hidden">
      <div className="mx-auto flex min-h-screen max-w-[1440px] flex-col px-5 sm:px-8 lg:px-12">
        <header className="flex h-20 items-center justify-between border-b border-white/8">
          <Link
            href="/"
            className="flex items-center gap-3 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
          >
            <LogoMark />

            <div>
              <p className="text-sm font-semibold tracking-tight text-white">
                AquaMind
              </p>
              <p className="hidden text-[11px] text-slate-500 sm:block">
                Water intelligence
              </p>
            </div>
          </Link>

          <div className="flex items-center gap-2">
            <a
              href="#capabilities"
              className="hidden rounded-lg px-4 py-2 text-sm text-slate-400 transition hover:text-white sm:inline-flex"
            >
              How it works
            </a>

            <Link
              href="/demo"
              className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 text-sm font-medium text-cyan-100 transition hover:border-cyan-300/35 hover:bg-cyan-300/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              Open demo
              <ArrowUpRight />
            </Link>
          </div>
        </header>

        <section className="grid flex-1 items-center gap-16 py-20 lg:grid-cols-[1.02fr_0.98fr] lg:py-24">
          <div className="max-w-3xl">
            <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-cyan-300/15 bg-cyan-300/5 px-3 py-1.5 text-xs font-medium text-cyan-100">
              <span className="size-1.5 rounded-full bg-cyan-300 shadow-[0_0_14px_rgba(103,232,249,0.9)]" />
              Multimodal household water intelligence
            </div>

            <h1 className="text-5xl font-semibold leading-[0.98] tracking-[-0.055em] text-white sm:text-6xl lg:text-7xl">
              Understand where your water is going.
            </h1>

            <p className="mt-7 max-w-2xl text-base leading-7 text-slate-400 sm:text-lg sm:leading-8">
              AquaMind combines water-meter data, images, voice, weather, and AI
              tools to investigate unusual household usage and recommend
              practical conservation actions.
            </p>

            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <Link
                href="/demo"
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-cyan-300 px-5 py-3.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
              >
                Try AquaMind
                <ArrowRight />
              </Link>

              <Link
                href="/analyze"
                className="inline-flex items-center justify-center rounded-xl border border-white/10 bg-white/[0.025] px-5 py-3.5 text-sm font-medium text-slate-200 transition hover:border-white/20 hover:bg-white/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
              >
                Analyze a bill
              </Link>
            </div>

            <div className="mt-10 flex flex-wrap gap-2">
              {signals.map((signal) => (
                <span
                  key={signal}
                  className="rounded-full border border-white/8 bg-white/[0.025] px-3 py-1.5 text-xs text-slate-500"
                >
                  {signal}
                </span>
              ))}
            </div>
          </div>

          <div className="relative lg:pl-8">
            <div className="absolute -inset-16 -z-10 rounded-full bg-cyan-400/5 blur-3xl" />

            <div className="overflow-hidden rounded-[28px] border border-white/10 bg-[#0b1724]/90 shadow-[0_40px_120px_rgba(0,0,0,0.35)] backdrop-blur">
              <div className="flex items-center justify-between border-b border-white/8 px-5 py-4 sm:px-6">
                <div>
                  <p className="text-sm font-medium text-slate-200">
                    Household overview
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Synthetic demonstration
                  </p>
                </div>

                <span className="rounded-full border border-amber-300/10 bg-amber-300/8 px-3 py-1 text-xs font-medium text-amber-200">
                  Attention
                </span>
              </div>

              <div className="p-5 sm:p-6">
                <div className="flex items-start justify-between gap-5">
                  <div>
                    <p className="text-sm text-slate-500">
                      Continuous overnight flow
                    </p>

                    <div className="mt-2 flex items-baseline gap-2">
                      <span className="text-4xl font-semibold tracking-tight text-white">
                        0.43
                      </span>
                      <span className="text-sm text-slate-500">gal/min</span>
                    </div>
                  </div>

                  <div className="rounded-xl border border-white/8 bg-white/[0.025] px-3 py-2 text-right">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-slate-600">
                      Status
                    </p>
                    <p className="mt-1 text-xs font-medium text-amber-200">
                      Elevated
                    </p>
                  </div>
                </div>

                <UsageChart />

                <div className="mt-5 grid grid-cols-3 gap-2.5">
                  <Metric label="Leak risk" value="Elevated" />
                  <Metric label="Since" value="1:15 AM" />
                  <Metric label="Est. excess" value="38 gal" />
                </div>

                <div className="mt-4 rounded-2xl border border-white/8 bg-[#08121d] p-4">
                  <div className="flex items-center gap-2">
                    <span className="flex size-6 items-center justify-center rounded-md bg-cyan-300/10 text-[10px] font-bold text-cyan-200">
                      AI
                    </span>
                    <p className="text-xs font-medium text-slate-400">
                      Example AquaMind insight
                    </p>
                  </div>

                  <p className="mt-3 text-sm leading-6 text-slate-300">
                    The overnight pattern is consistent with continuous flow. A
                    running toilet or dripping fixture would be worth checking
                    first.
                  </p>
                </div>
              </div>
            </div>

            <div className="absolute -bottom-5 -left-4 hidden rounded-2xl border border-white/10 bg-[#0b1724]/95 px-4 py-3 shadow-2xl backdrop-blur sm:block">
              <p className="text-[10px] uppercase tracking-[0.18em] text-slate-600">
                Inputs
              </p>
              <p className="mt-1 text-xs text-slate-300">
                Meter · Weather · Image · Voice
              </p>
            </div>
          </div>
        </section>

        <section
          id="capabilities"
          className="grid gap-px overflow-hidden rounded-2xl border border-white/8 bg-white/8 md:grid-cols-3"
        >
          {capabilities.map((capability) => (
            <article
              key={capability.number}
              className="bg-[#09131f] p-6 sm:p-7"
            >
              <p className="font-mono text-xs text-cyan-300/70">
                {capability.number}
              </p>

              <h2 className="mt-8 text-lg font-medium tracking-tight text-white">
                {capability.title}
              </h2>

              <p className="mt-3 max-w-sm text-sm leading-6 text-slate-500">
                {capability.description}
              </p>
            </article>
          ))}
        </section>

        <footer className="flex flex-col gap-2 py-8 text-xs text-slate-600 sm:flex-row sm:items-center sm:justify-between">
          <p>AquaMind · Multimodal water intelligence</p>
          <p>Built as a production AI engineering project.</p>
        </footer>
      </div>
    </main>
  );
}

function UsageChart() {
  const values = [
    22, 18, 16, 14, 13, 13, 14, 13, 14, 13, 14, 14, 33, 46, 61, 48, 36, 31,
    28, 24, 21, 18, 16, 15,
  ];

  return (
    <div className="mt-7">
      <div className="mb-2 flex items-center justify-between text-[10px] uppercase tracking-[0.16em] text-slate-600">
        <span>12 AM</span>
        <span>12 PM</span>
        <span>Now</span>
      </div>

      <div
        aria-label="Illustrative household water usage chart"
        className="flex h-36 items-end gap-1 rounded-2xl border border-white/8 bg-[#08121d] p-4"
      >
        {values.map((value, index) => (
          <div
            key={`${value}-${index}`}
            className="min-w-0 flex-1 rounded-sm bg-cyan-300/65"
            style={{ height: `${value + 20}%` }}
          />
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-white/8 bg-white/[0.02] p-3">
      <p className="truncate text-[10px] text-slate-600">{label}</p>
      <p className="mt-1 truncate text-xs font-medium text-slate-200">
        {value}
      </p>
    </div>
  );
}

function LogoMark() {
  return (
    <span
      aria-hidden="true"
      className="relative flex size-9 items-center justify-center overflow-hidden rounded-xl border border-cyan-300/15 bg-cyan-300/10"
    >
      <span className="absolute size-4 rotate-45 rounded-[4px] border border-cyan-200/70" />
      <span className="size-1.5 rounded-full bg-cyan-200" />
    </span>
  );
}

function ArrowRight() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      className="size-4"
      fill="none"
    >
      <path
        d="M4 10h12m-4-4 4 4-4 4"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ArrowUpRight() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      className="size-3.5"
      fill="none"
    >
      <path
        d="M6 14 14 6m-6 0h6v6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
