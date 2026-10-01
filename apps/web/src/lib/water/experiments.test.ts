import { describe, expect, it } from "vitest";
import { createMeterExperimentDataset, generateHouseholdDataset } from "./index";

const seeds = Array.from({ length: 30 }, (_, seed) => seed);

describe("createMeterExperimentDataset", () => {
  it("keeps all windows and scenario variants within their assigned seed split", () => {
    const dataset = createMeterExperimentDataset(seeds);
    for (const split of ["train", "validation", "test"] as const) {
      expect(dataset.seedSplit[split].length).toBeGreaterThan(0);
      expect(new Set(dataset[split].map((window) => window.seed)))
        .toEqual(new Set(dataset.seedSplit[split]));
      const otherSeeds = new Set(
        ["train", "validation", "test"].filter((name) => name !== split)
          .flatMap((name) => dataset.seedSplit[name as keyof typeof dataset.seedSplit]),
      );
      expect(dataset[split].every((window) => !otherSeeds.has(window.seed))).toBe(true);
    }
  });

  it("trains only on normal sequences and avoids duplicated history in evaluation", () => {
    const dataset = createMeterExperimentDataset(seeds);
    expect(dataset.train).toHaveLength(dataset.seedSplit.train.length * 7);
    expect(dataset.train.every((window) =>
      window.scenarioId === "normal" && !window.hasAnomaly && !window.hasLeak,
    )).toBe(true);
    for (const split of ["validation", "test"] as const) {
      for (const seed of dataset.seedSplit[split]) {
        const windows = dataset[split].filter((window) => window.seed === seed);
        expect(windows).toHaveLength(10);
        expect(windows.filter((window) => window.scenarioId === "normal")).toHaveLength(7);
        expect(windows.filter((window) => window.hasAnomaly)).toHaveLength(3);
        expect(windows.filter((window) => window.hasLeak).map((window) => window.scenarioId))
          .toEqual(["overnight-leak", "running-toilet"]);
      }
    }
  });

  it("preserves raw meter features separately from provenance and synthetic labels", () => {
    const dataset = createMeterExperimentDataset(seeds);
    expect(dataset.source).toBe("synthetic");
    for (const window of [...dataset.train, ...dataset.validation, ...dataset.test]) {
      const source = generateHouseholdDataset(window.scenarioId, window.seed).readings
        .filter((reading) => reading.timestamp >= window.startTimestamp &&
          reading.timestamp <= window.endTimestamp);
      expect(window.flowRatesGpm).toHaveLength(96);
      expect(window.flowRatesGpm).toEqual(source.map((reading) => reading.flowRateGpm));
      expect(window.hasAnomaly).toBe(source.some((reading) => reading.isAnomaly));
    }
  });

  it("is reproducible regardless of seed order or duplicates and serializes as JSON", () => {
    const input = [...seeds].reverse();
    const original = [...input];
    const dataset = createMeterExperimentDataset(input);
    expect(createMeterExperimentDataset([...seeds, ...seeds])).toEqual(dataset);
    expect(JSON.parse(JSON.stringify(dataset))).toEqual(dataset);
    expect(input).toEqual(original);
  });

  it("allows empty splits and rejects invalid seeds before generating data", () => {
    const dataset = createMeterExperimentDataset([]);
    expect(dataset.train).toEqual([]);
    expect(dataset.validation).toEqual([]);
    expect(dataset.test).toEqual([]);
    expect(() => createMeterExperimentDataset([0, -1])).toThrow(/unsigned 32-bit/);
  });
});
