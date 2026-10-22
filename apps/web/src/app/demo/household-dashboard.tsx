"use client";

import { SCENARIOS } from "@/lib/water";
import type { HouseholdDataset, MeterReading, ScenarioId } from "@/lib/water";

export function HouseholdDashboard({ dataset, onScenarioChange }: {
  dataset: HouseholdDataset;
  onScenarioChange: (scenarioId: ScenarioId) => void;
}) {
  const { scenario, summary, readings } = dataset;
  const today = readings.slice(-96);

  return (
    <>
      <aside className="rounded-2xl border border-white/8 bg-white/[0.02] p-4 lg:min-h-[calc(100vh-6.5rem)]">
        <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-slate-600">
          Demo scenarios
        </p>

        <div className="mt-4 space-y-2">
          {Object.values(SCENARIOS).map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => onScenarioChange(option.id)}
              aria-pressed={option.id === scenario.id}
              className={`w-full cursor-pointer rounded-xl border p-3 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 ${
                option.id === scenario.id
                  ? "border-cyan-300/15 bg-cyan-300/[0.06]"
                  : "border-transparent hover:border-white/8 hover:bg-white/[0.025]"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-medium text-slate-200">
                  {option.title}
                </p>

                {option.id === scenario.id ? (
                  <span className="mt-1 size-1.5 shrink-0 rounded-full bg-cyan-300" />
                ) : null}
              </div>

              <p className="mt-2 text-xs leading-5 text-slate-600">
                {option.description}
              </p>
            </button>
          ))}
        </div>

        <div className="mt-8 rounded-xl border border-dashed border-white/10 p-3">
          <p className="text-xs font-medium text-slate-400">
            Deterministic household
          </p>
          <p className="mt-1.5 text-xs leading-5 text-slate-600">
            Seven synthetic days, seeded household events, and a rule-defined
            anomaly window. Select a scenario to compare usage in the same household.
          </p>
        </div>
      </aside>

      <section className="min-w-0 space-y-4" aria-label="Household usage dashboard">
        <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
          {scenario.title}: {summary.todayGallons.toFixed(1)} gallons.
          {summary.anomalyDetected ? ` ${summary.excessGallons.toFixed(1)} gallons of generated excess usage.` : " No generated anomaly."}
        </p>
        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
          <SummaryCard
            label="Simulated day"
            value={`${summary.todayGallons.toFixed(1)} gal`}
            detail={`${summary.differencePct > 0 ? "+" : ""}${summary.differencePct.toFixed(1)}% vs ${summary.baselineDailyGallons.toFixed(1)} gal baseline`}
          />
          <SummaryCard
            label="Peak excess flow"
            value={summary.anomalyFlowRateGpm?.toFixed(2) ?? "—"}
            unit="gal/min"
            detail={`${summary.excessGallons.toFixed(1)} gal excess in defined window`}
          />
          <SummaryCard
            label="Scenario status"
            value={scenario.status}
            detail={summary.anomalyStart ? `Starts ${formatTime(summary.anomalyStart)} UTC` : "No generated anomaly"}
          />
        </div>

        <div className="rounded-2xl border border-white/8 bg-white/[0.02] p-5 sm:p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-sm font-medium text-slate-200">
                Household water usage
              </p>
              <p className="mt-1 text-xs text-slate-600">
                {today[0].timestamp.slice(0, 10)} · 15-minute intervals · synthetic data · UTC
              </p>
            </div>

            <span className={`w-fit rounded-full border px-3 py-1 text-xs ${summary.anomalyDetected ? "border-amber-300/10 bg-amber-300/[0.06] text-amber-200" : "border-cyan-300/10 bg-cyan-300/[0.06] text-cyan-200"}`}>
              {summary.anomalyDetected ? "Rule-defined anomaly" : "Normal usage"}
            </span>
          </div>

          <UsageChart readings={today} />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <InfoPanel
            eyebrow="Synthetic scenario"
            title={scenario.title}
            body={`${scenario.description} ${scenario.id === "irrigation-after-rain" ? "This is a conservation opportunity, not evidence of a physical leak." : "Anomaly flags are defined by the simulator, not a machine-learning prediction."}`}
          />

          <InfoPanel
            eyebrow="Synthetic environmental context"
            title={`${scenario.rainfallInchesLast24h.toFixed(2)} in rain in the last 24 hours`}
            body={`${scenario.temperatureF}°F. Weather context is part of this synthetic scenario. The usage baseline is the mean of the preceding six simulated days.`}
          />
        </div>
      </section>
    </>
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

      <div className="mt-2 flex flex-wrap items-baseline gap-1.5">
        <span className="break-words text-2xl font-semibold tracking-tight text-white">
          {value}
        </span>

        {unit ? <span className="text-xs text-slate-600">{unit}</span> : null}
      </div>

      <p className="mt-2 text-xs text-slate-500">{detail}</p>
    </article>
  );
}

function formatTime(timestamp: string) {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(timestamp));
}

function UsageChart({ readings }: { readings: MeterReading[] }) {
  const maximum = Math.max(1, ...readings.map((reading) => reading.gallons));

  return (
    <figure className="mt-7">
      <figcaption className="mb-3 text-xs text-slate-400">
        Gallons per interval · scale 0–{maximum.toFixed(1)} gal
        <span className="mt-1 block">Cyan: ordinary usage · Amber: rule-defined anomaly</span>
      </figcaption>
      <svg
        viewBox="0 0 960 240"
        role="img"
        aria-label="96 meter intervals for the final simulated day; amber bars mark injected anomalies. Interval values are available below."
        className="h-64 w-full rounded-xl border border-white/8 bg-[#07111b] p-3"
        preserveAspectRatio="none"
      >
        {readings.map((reading, index) => {
          const height = (reading.gallons / maximum) * 230;
          return (
            <rect
              key={reading.timestamp}
              x={index * 10}
              y={240 - height}
              width={8}
              height={height}
              fill={reading.isAnomaly ? "#fcd34d" : "#67e8f9"}
              opacity={0.75}
            >
              <title>{`${formatTime(reading.timestamp)} UTC: ${reading.gallons.toFixed(3)} gal${reading.isAnomaly ? " (generated anomaly)" : ""}`}</title>
            </rect>
          );
        })}
      </svg>
      <div className="mt-2 flex justify-between text-[10px] text-slate-400">
        <span>12 AM</span><span>6 AM</span><span>12 PM</span><span>6 PM</span><span>12 AM</span>
      </div>
      <details className="mt-4 text-xs text-slate-400">
        <summary className="cursor-pointer rounded focus-visible:outline-2 focus-visible:outline-cyan-300">View interval data (UTC)</summary>
        <div className="mt-3 max-h-64 overflow-auto">
          <table className="w-full text-left tabular-nums">
            <caption className="sr-only">Synthetic meter readings for the final day</caption>
            <thead><tr><th scope="col">Time</th><th scope="col">Gallons</th><th scope="col">Excess</th><th scope="col">Anomaly</th></tr></thead>
            <tbody>{readings.map((reading) => (
              <tr key={reading.timestamp} className="border-t border-white/8">
                <th scope="row" className="py-2 font-normal">{formatTime(reading.timestamp)}</th>
                <td>{reading.gallons.toFixed(3)}</td><td>{reading.excessGallons.toFixed(3)}</td><td>{reading.isAnomaly ? "Yes" : "No"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </details>
    </figure>
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
