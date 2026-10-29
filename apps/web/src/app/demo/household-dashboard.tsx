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
    <section className="min-w-0 space-y-6" aria-label="Household usage dashboard">
      <div className="min-w-0 xl:hidden">
        <div className="flex flex-wrap items-center justify-between gap-x-4">
          <label htmlFor="demo-scenario" className="text-sm font-medium text-ink">Demo scenario</label>
          <a href="#assistant-heading" className="ui-link text-accent">Ask AquaMind</a>
        </div>
        <select id="demo-scenario" name="scenario" className="ui-field" value={scenario.id}
          onChange={(event) => {
            const option = Object.values(SCENARIOS).find((item) => item.id === event.target.value);
            if (option) onScenarioChange(option.id);
          }}>
          {Object.values(SCENARIOS).map((option) => <option key={option.id} value={option.id}>{option.title}</option>)}
        </select>
      </div>

      <div className="hidden xl:block">
        <p className="text-sm font-medium text-ink">
          Demo scenarios
        </p>

        <div className="mt-3 grid grid-cols-4 gap-2">
          {Object.values(SCENARIOS).map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => onScenarioChange(option.id)}
              aria-pressed={option.id === scenario.id}
              className={`scenario-option min-h-11 cursor-pointer rounded-control border p-3 text-left text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${
                option.id === scenario.id
                  ? "border-accent bg-accent-soft"
                  : "border-rule hover:bg-surface-raised"
              }`}
            >
              {option.title}
            </button>
          ))}
        </div>

      </div>

      <div className="space-y-6">
        <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
          {scenario.title}: {summary.todayGallons.toFixed(1)} gallons.
          {summary.anomalyDetected ? ` ${summary.excessGallons.toFixed(1)} gallons of generated excess usage.` : " No generated anomaly."}
        </p>
        <div className="divide-y divide-rule border-y border-rule sm:grid sm:grid-cols-3 sm:divide-x sm:divide-y-0">
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

        <div className="rounded-panel border border-rule bg-surface p-5 sm:p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-sm font-medium text-ink">
                Household water usage
              </h2>
              <p className="mt-1 text-xs text-muted">
                {today[0].timestamp.slice(0, 10)}, 15-minute intervals, synthetic data, UTC
              </p>
            </div>

            <span className={`w-fit rounded-full border px-3 py-1 text-xs ${summary.anomalyDetected ? "border-warning bg-warning-soft text-warning" : "border-rule bg-accent-soft text-accent"}`}>
              {summary.anomalyDetected ? "Rule-defined anomaly" : "Normal usage"}
            </span>
          </div>

          <UsageChart readings={today} />
        </div>

        <div className="hidden xl:block">
          <ScenarioContext dataset={dataset} />
        </div>
        <details className="border-t border-rule pt-3 xl:hidden">
          <summary className="ui-link cursor-pointer list-item text-accent">Scenario and weather details</summary>
          <div className="mt-3"><ScenarioContext dataset={dataset} /></div>
        </details>
      </div>
    </section>
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
    <article className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 gap-y-1 py-3 sm:block sm:p-4">
      <p className="text-xs text-muted">{label}</p>

      <div className="flex flex-wrap items-baseline gap-1.5 sm:mt-2">
        <span className="break-words text-2xl font-semibold tracking-tight text-ink tabular-nums">
          {value}
        </span>

        {unit ? <span className="text-xs text-muted">{unit}</span> : null}
      </div>

      <p className="col-span-2 text-xs text-muted sm:mt-2">{detail}</p>
    </article>
  );
}

function ScenarioContext({ dataset }: { dataset: HouseholdDataset }) {
  const { scenario } = dataset;
  return <div className="space-y-4">
    <div className="grid gap-6 md:grid-cols-2">
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
    <p className="text-xs leading-5 text-muted">Seven synthetic days, seeded household events, and a rule-defined anomaly window. Select a scenario to compare usage in the same household.</p>
  </div>;
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
      <figcaption className="mb-3 text-xs text-muted">
        Gallons per interval, scale 0 to {maximum.toFixed(1)} gal
        <span className="mt-1 block">Charcoal: ordinary usage. Terracotta: rule-defined anomaly.</span>
      </figcaption>
      <svg
        viewBox="0 0 960 240"
        role="img"
        aria-label="96 meter intervals for the final simulated day; terracotta bars mark injected anomalies. Interval values are available below."
        className="h-64 w-full"
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
              fill={reading.isAnomaly ? "var(--color-chart-anomaly)" : "var(--color-chart-usage)"}
            >
              <title>{`${formatTime(reading.timestamp)} UTC: ${reading.gallons.toFixed(3)} gal${reading.isAnomaly ? " (generated anomaly)" : ""}`}</title>
            </rect>
          );
        })}
      </svg>
      <div className="mt-2 flex justify-between text-xs text-muted tabular-nums">
        <span>12 AM</span><span>6 AM</span><span>12 PM</span><span>6 PM</span><span>12 AM</span>
      </div>
      <details className="mt-4 text-xs text-muted">
        <summary className="cursor-pointer rounded focus-visible:outline-2 focus-visible:outline-focus">View interval data (UTC)</summary>
        <div className="mt-3 max-h-64 overflow-auto">
          <table className="w-full text-left tabular-nums">
            <caption className="sr-only">Synthetic meter readings for the final day</caption>
            <thead><tr><th scope="col">Time</th><th scope="col">Gallons</th><th scope="col">Excess</th><th scope="col">Anomaly</th></tr></thead>
            <tbody>{readings.map((reading) => (
              <tr key={reading.timestamp} className="border-t border-rule">
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
    <article>
      <h3 className="text-sm font-medium text-ink">{title}</h3>

      <p className="mt-2 text-sm leading-6 text-muted">{body}</p>
      <p className="mt-3 text-xs text-muted">{eyebrow}</p>
    </article>
  );
}
