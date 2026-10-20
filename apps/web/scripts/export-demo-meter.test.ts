import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { generateHouseholdDataset } from "../src/lib/water/generator";
import { SCENARIOS } from "../src/lib/water/scenarios";
import { demoMeterBytes } from "./export-demo-meter";

describe("demo meter snapshot", () => {
  it("keeps the committed snapshot synchronized with all four dashboard scenarios", () => {
    const bytes = demoMeterBytes();
    expect(readFileSync(resolve(__dirname, "../../../ml/data/demo/meter-v1.json"), "utf8")).toBe(bytes);
    const snapshot = JSON.parse(bytes);
    expect(snapshot.source).toBe("synthetic");
    expect(snapshot.seed).toBe(42);
    expect(Object.keys(snapshot.scenarios).sort()).toEqual(Object.keys(SCENARIOS).sort());
    for (const { id } of Object.values(SCENARIOS)) {
      const dashboard = generateHouseholdDataset(id);
      const gallons: number[] = snapshot.scenarios[id];
      expect(gallons).toEqual(dashboard.readings.map((reading) => reading.gallons));
      expect(gallons).toHaveLength(672);
      expect(snapshot.start_timestamp).toBe(dashboard.readings[0].timestamp);
      const total = gallons.slice(-96).reduce((sum, value) => sum + value, 0);
      const baseline = gallons.slice(0, -96).reduce((sum, value) => sum + value, 0) / 6;
      expect(Number(total.toFixed(1))).toBe(dashboard.summary.todayGallons);
      expect(Number(baseline.toFixed(1))).toBe(dashboard.summary.baselineDailyGallons);
    }
    for (const label of ["isAnomaly", "hasLeak", "fixtures", "excessGallons"]) {
      expect(bytes).not.toContain(label);
    }
    expect(demoMeterBytes()).toBe(bytes);
  });
});
