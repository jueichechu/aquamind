import { describe, expect, it } from "vitest";
import { generateHouseholdDataset, SCENARIOS } from "./index";
import type { ScenarioId } from "./types";

const scenarioIds = Object.keys(SCENARIOS) as ScenarioId[];
const intervalMs = 15 * 60_000;

describe.each(scenarioIds)("%s dataset", (scenarioId) => {
  it("contains seven complete days on a continuous 15-minute UTC grid", () => {
    const { readings } = generateHouseholdDataset(scenarioId);
    expect(readings).toHaveLength(672);
    const days = new Map<string, number>();
    readings.forEach((reading, index) => {
      expect(new Date(reading.timestamp).toISOString()).toBe(reading.timestamp);
      if (index > 0) {
        expect(Date.parse(reading.timestamp) - Date.parse(readings[index - 1].timestamp)).toBe(intervalMs);
      }
      const day = reading.timestamp.slice(0, 10);
      days.set(day, (days.get(day) ?? 0) + 1);
    });
    expect(days.size).toBe(7);
    expect([...days.values()]).toEqual(Array(7).fill(96));
  });

  it("is reproducible for the same seed and varies across seeds", () => {
    expect(generateHouseholdDataset(scenarioId, 123)).toEqual(generateHouseholdDataset(scenarioId, 123));
    expect(generateHouseholdDataset(scenarioId, 123).readings).not.toEqual(generateHouseholdDataset(scenarioId, 456).readings);
    expect(generateHouseholdDataset(scenarioId)).toEqual(generateHouseholdDataset(scenarioId, 42));
  });

  it.each([0, 42, 123, 4294967295])("has finite, non-negative attributed usage for seed %i", (seed) => {
    for (const reading of generateHouseholdDataset(scenarioId, seed).readings) {
      expect(Number.isFinite(reading.gallons)).toBe(true);
      expect(reading.gallons).toBeGreaterThanOrEqual(0);
      expect(reading.excessGallons).toBeGreaterThanOrEqual(0);
      expect(reading.excessGallons).toBeLessThanOrEqual(reading.gallons);
      expect(reading.flowRateGpm).toBeCloseTo(reading.gallons / 15, 3);
      expect(reading.fixtures.length).toBeGreaterThan(0);
      expect(new Set(reading.fixtures).size).toBe(reading.fixtures.length);
    }
  });

  it("derives its summary from the last day and six preceding baseline days", () => {
    const { readings, summary } = generateHouseholdDataset(scenarioId);
    const today = readings.slice(-96);
    const history = readings.slice(0, -96);
    const todayTotal = today.reduce((sum, reading) => sum + reading.gallons, 0);
    const baseline = history.reduce((sum, reading) => sum + reading.gallons, 0) / 6;
    const anomalies = today.filter((reading) => reading.isAnomaly);
    const excess = today.reduce((sum, reading) => sum + reading.excessGallons, 0);
    expect(summary.todayGallons).toBeCloseTo(todayTotal, 1);
    expect(summary.baselineDailyGallons).toBeCloseTo(baseline, 1);
    expect(summary.differencePct).toBeCloseTo((todayTotal / baseline - 1) * 100, 1);
    expect(summary.excessGallons).toBeCloseTo(excess, 1);
    expect(summary.anomalyDetected).toBe(anomalies.length > 0);
    expect(summary.anomalyStart).toBe(anomalies[0]?.timestamp ?? null);
    if (anomalies.length) {
      expect(summary.anomalyFlowRateGpm).toBeCloseTo(Math.max(...anomalies.map((reading) => reading.excessGallons / 15)), 2);
    } else {
      expect(summary.anomalyFlowRateGpm).toBeNull();
    }
    expect(history.every((reading) => !reading.isAnomaly && reading.excessGallons === 0)).toBe(true);
  });
});

describe("scenario patterns", () => {
  it("keeps normal readings free of injected anomalies", () => {
    const { readings, summary } = generateHouseholdDataset("normal");
    expect(readings.every((reading) => !reading.isAnomaly && reading.excessGallons === 0)).toBe(true);
    expect(summary.anomalyDetected).toBe(false);
    expect(summary.excessGallons).toBe(0);
    expect(new Set(readings.flatMap((reading) => reading.fixtures))).toEqual(new Set([
      "baseline", "shower", "toilet", "faucet", "dishwasher", "washer", "irrigation",
    ]));
  });

  it("injects constant leak flow from 01:15 up to 06:00 on the final day", () => {
    const { readings, summary } = generateHouseholdDataset("overnight-leak");
    const anomalies = readings.filter((reading) => reading.isAnomaly);
    expect(anomalies).toHaveLength(19);
    expect(anomalies[0].timestamp.slice(11, 16)).toBe("01:15");
    expect(anomalies.at(-1)?.timestamp.slice(11, 16)).toBe("05:45");
    expect(new Set(anomalies.map((reading) => reading.excessGallons)).size).toBe(1);
    expect(anomalies.every((reading) => reading.fixtures.includes("leak"))).toBe(true);
    expect(summary.excessGallons).toBeGreaterThan(0);
  });

  it("injects intermittent toilet refills with ordinary intervals between them", () => {
    const today = generateHouseholdDataset("running-toilet").readings.slice(-96);
    const indices = today.flatMap((reading, index) => reading.isAnomaly ? [index] : []);
    expect(indices.length).toBeGreaterThan(5);
    indices.forEach((index, position) => {
      expect(today[index].fixtures).toContain("toilet");
      expect(today[index].excessGallons).toBeGreaterThan(0);
      if (position > 0) expect(index - indices[position - 1]).toBeGreaterThan(1);
    });
  });

  it("provides rainfall context for an anomalous irrigation opportunity", () => {
    const { scenario, readings } = generateHouseholdDataset("irrigation-after-rain");
    expect(scenario.rainfallInchesLast24h).toBeGreaterThan(0);
    expect(scenario.status).toBe("Opportunity");
    const anomalies = readings.filter((reading) => reading.isAnomaly);
    expect(anomalies.length).toBeGreaterThan(0);
    expect(anomalies.every((reading) => reading.fixtures.includes("irrigation") && !reading.fixtures.includes("leak") && reading.excessGallons > 0)).toBe(true);
  });

  it.each(scenarioIds.filter((id) => id !== "normal"))("preserves normal household usage underneath %s", (id) => {
    const normal = generateHouseholdDataset("normal").readings;
    const scenario = generateHouseholdDataset(id).readings;
    scenario.forEach((reading, index) => {
      expect(reading.gallons - reading.excessGallons).toBeCloseTo(normal[index].gallons, 2);
      if (!reading.isAnomaly) expect(reading).toEqual(normal[index]);
    });
  });
});
