import { generateHouseholdDataset } from "./generator";
import { splitHouseholdSeeds, type HouseholdSeedSplit } from "./splits";
import type { ScenarioId } from "./types";
import { createMeterWindows, type MeterWindow } from "./windows";

export interface ExperimentWindow extends MeterWindow {
  seed: number;
  scenarioId: ScenarioId;
  /** Synthetic physical-leak label; irrigation opportunities are not leaks. */
  hasLeak: boolean;
}

export interface MeterExperimentDataset {
  schemaVersion: 1;
  source: "synthetic";
  intervalMinutes: 15;
  windowSize: 96;
  seedSplit: HouseholdSeedSplit;
  train: ExperimentWindow[];
  validation: ExperimentWindow[];
  test: ExperimentWindow[];
}

/** Raw daily sequences: normal-only training, held-out scenario evaluation. */
export function createMeterExperimentDataset(
  seeds: readonly number[],
): MeterExperimentDataset {
  const seedSplit = splitHouseholdSeeds(seeds);
  const dataset: MeterExperimentDataset = {
    schemaVersion: 1,
    source: "synthetic",
    intervalMinutes: 15,
    windowSize: 96,
    seedSplit,
    train: [],
    validation: [],
    test: [],
  };

  for (const split of ["train", "validation", "test"] as const) {
    for (const seed of seedSplit[split]) {
      const normal = generateHouseholdDataset("normal", seed);
      dataset[split].push(...createMeterWindows(normal.readings).map((window) => ({
        ...window, seed, scenarioId: "normal" as const, hasLeak: false,
      })));

      if (split === "train") continue;

      for (const scenarioId of [
        "overnight-leak", "running-toilet", "irrigation-after-rain",
      ] as const) {
        const scenario = generateHouseholdDataset(scenarioId, seed);
        // Variants share their first six days; include those days only once above.
        const windows = createMeterWindows(scenario.readings.slice(-96));
        dataset[split].push(...windows.map((window) => ({
          ...window,
          seed,
          scenarioId,
          hasLeak: window.hasAnomaly && scenarioId !== "irrigation-after-rain",
        })));
      }
    }
  }

  return dataset;
}
