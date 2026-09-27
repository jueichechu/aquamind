import type { MeterReading } from "./types";

export interface MeterWindow {
  startTimestamp: string;
  endTimestamp: string;
  flowRatesGpm: number[];
  /** Synthetic ground truth, never an input feature; includes conservation anomalies. */
  hasAnomaly: boolean;
}

/** Build complete windows from one household's ordered 15-minute readings. */
export function createMeterWindows(
  readings: readonly MeterReading[],
  windowSize = 96,
  stride = windowSize,
): MeterWindow[] {
  if (!Number.isSafeInteger(windowSize) || windowSize < 1) {
    throw new RangeError("windowSize must be a positive safe integer");
  }
  if (!Number.isSafeInteger(stride) || stride < 1) {
    throw new RangeError("stride must be a positive safe integer");
  }

  const intervalMs = 15 * 60_000;
  let previousTimestamp: number | undefined;
  for (const reading of readings) {
    const timestamp = Date.parse(reading.timestamp);
    if (!Number.isFinite(timestamp)) {
      throw new RangeError("Readings must have valid timestamps");
    }
    if (previousTimestamp !== undefined && timestamp - previousTimestamp !== intervalMs) {
      throw new RangeError("Readings must be ordered at uninterrupted 15-minute intervals");
    }
    if (!Number.isFinite(reading.flowRateGpm) || reading.flowRateGpm < 0) {
      throw new RangeError("Flow rates must be finite and non-negative");
    }
    previousTimestamp = timestamp;
  }

  const windows: MeterWindow[] = [];
  // Drop incomplete tails instead of inventing padded meter observations.
  for (let start = 0; start <= readings.length - windowSize; start += stride) {
    const window = readings.slice(start, start + windowSize);
    windows.push({
      startTimestamp: window[0].timestamp,
      endTimestamp: window[window.length - 1].timestamp,
      flowRatesGpm: window.map((reading) => reading.flowRateGpm),
      hasAnomaly: window.some((reading) => reading.isAnomaly),
    });
  }
  return windows;
}
