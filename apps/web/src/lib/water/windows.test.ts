import { describe, expect, it } from "vitest";
import { createMeterWindows, generateHouseholdDataset } from "./index";

const readings = generateHouseholdDataset("overnight-leak").readings;

describe("createMeterWindows", () => {
  it("creates seven daily windows with flow inputs and separate synthetic labels", () => {
    const windows = createMeterWindows(readings);
    expect(windows).toHaveLength(7);
    windows.forEach((window, day) => {
      const source = readings.slice(day * 96, (day + 1) * 96);
      expect(window.flowRatesGpm).toEqual(source.map((reading) => reading.flowRateGpm));
      expect(window.startTimestamp).toBe(source[0].timestamp);
      expect(window.endTimestamp).toBe(source[95].timestamp);
      expect(window.hasAnomaly).toBe(day === 6);
    });
  });

  it("supports overlapping windows without padding incomplete tails", () => {
    const windows = createMeterWindows(readings.slice(0, 11), 4, 3);
    expect(windows).toHaveLength(3);
    expect(windows.map((window) => window.startTimestamp)).toEqual(
      [0, 3, 6].map((index) => readings[index].timestamp),
    );
    expect(windows[2].endTimestamp).toBe(readings[9].timestamp);
    expect(createMeterWindows(readings.slice(0, 3), 4)).toEqual([]);
    expect(createMeterWindows([])).toEqual([]);
  });

  it("does not classify ordinary usage as anomalous", () => {
    const normal = generateHouseholdDataset("normal");
    expect(createMeterWindows(normal.readings).every((window) => !window.hasAnomaly)).toBe(true);
  });

  it("keeps conservation anomalies in ground truth without calling them leaks", () => {
    const irrigation = generateHouseholdDataset("irrigation-after-rain");
    expect(createMeterWindows(irrigation.readings).at(-1)?.hasAnomaly).toBe(true);
  });

  it("returns independent feature arrays and leaves input readings unchanged", () => {
    const original = structuredClone(readings);
    const windows = createMeterWindows(readings, 4, 1);
    windows[0].flowRatesGpm[1] = 999;
    expect(windows[1].flowRatesGpm[0]).toBe(readings[1].flowRateGpm);
    expect(readings).toEqual(original);
    expect(createMeterWindows(readings)).toEqual(createMeterWindows(original));
  });

  it.each([0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])(
    "rejects invalid window sizes and strides: %s", (value) => {
      expect(() => createMeterWindows(readings, value)).toThrow(RangeError);
      expect(() => createMeterWindows(readings, 4, value)).toThrow(RangeError);
    },
  );

  it("rejects missing, duplicate, reversed, and invalid timestamps", () => {
    expect(() => createMeterWindows([readings[0], readings[2]])).toThrow(/15-minute/);
    expect(() => createMeterWindows([readings[0], readings[0]])).toThrow(/15-minute/);
    expect(() => createMeterWindows([readings[1], readings[0]])).toThrow(/15-minute/);
    expect(() => createMeterWindows([{ ...readings[0], timestamp: "invalid" }])).toThrow(/timestamps/);
  });

  it.each([-1, NaN, Infinity])("rejects invalid flow rates: %s", (flowRateGpm) => {
    expect(() => createMeterWindows([{ ...readings[0], flowRateGpm }])).toThrow(/Flow rates/);
  });
});
