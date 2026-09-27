import { SCENARIOS } from "./scenarios";
import type {
  FixtureKind,
  HouseholdDataset,
  MeterReading,
  ScenarioId,
} from "./types";

const INTERVAL_MINUTES = 15;
const INTERVALS_PER_DAY = (24 * 60) / INTERVAL_MINUTES;
const DEFAULT_DAYS = 7;
const DEFAULT_SEED = 42;

type MutableReading = {
  timestamp: string;
  gallons: number;
  fixtures: Set<FixtureKind>;
  isAnomaly: boolean;
  excessGallons: number;
};

export function generateHouseholdDataset(
  scenarioId: ScenarioId,
  seed = DEFAULT_SEED,
): HouseholdDataset {
  const random = createRandom(seed);
  const scenario = { ...SCENARIOS[scenarioId] };

  const start = new Date("2026-06-15T00:00:00.000Z");

  const readings = createEmptyReadings(start, DEFAULT_DAYS);

  for (let day = 0; day < DEFAULT_DAYS; day += 1) {
    generateNormalDay(readings, day, random);
  }

  const anomalyDay = DEFAULT_DAYS - 1;

  switch (scenarioId) {
    case "overnight-leak":
      addOvernightLeak(readings, anomalyDay);
      break;

    case "running-toilet":
      addRunningToilet(readings, anomalyDay, random);
      break;

    case "irrigation-after-rain":
      addIrrigationAfterRain(readings, anomalyDay);
      break;

    case "normal":
      break;
  }

  const finalizedReadings = readings.map(finalizeReading);

  return {
    scenario,
    readings: finalizedReadings,
    summary: calculateSummary(finalizedReadings),
  };
}

function createEmptyReadings(
  start: Date,
  days: number,
): MutableReading[] {
  const count = days * INTERVALS_PER_DAY;

  return Array.from({ length: count }, (_, index) => {
    const timestamp = new Date(
      start.getTime() + index * INTERVAL_MINUTES * 60_000,
    );

    return {
      timestamp: timestamp.toISOString(),
      gallons: 0,
      fixtures: new Set<FixtureKind>(),
      isAnomaly: false,
      excessGallons: 0,
    };
  });
}

function generateNormalDay(
  readings: MutableReading[],
  day: number,
  random: () => number,
) {
  addBaseline(readings, day, random);

  const occupants = 3;

  for (let person = 0; person < occupants; person += 1) {
    addDailyShower(readings, day, person, random);
    addToiletUses(readings, day, random);
    addFaucetUses(readings, day, random);
  }

  if (random() < 0.72) {
    addDishwasher(readings, day, random);
  }

  if (random() < 0.48) {
    addWasher(readings, day, random);
  }

  if (random() < 0.28) {
    addNormalIrrigation(readings, day, random);
  }
}

function addBaseline(
  readings: MutableReading[],
  day: number,
  random: () => number,
) {
  for (let slot = 0; slot < INTERVALS_PER_DAY; slot += 1) {
    const index = day * INTERVALS_PER_DAY + slot;

    const hour = (slot * INTERVAL_MINUTES) / 60;

    const activeHour =
      (hour >= 6 && hour <= 9) ||
      (hour >= 17 && hour <= 22);

    const gallons =
      activeHour
        ? randomBetween(random, 0.03, 0.12)
        : randomBetween(random, 0, 0.035);

    addUsage(readings, index, gallons, "baseline");
  }
}

function addDailyShower(
  readings: MutableReading[],
  day: number,
  person: number,
  random: () => number,
) {
  if (random() > 0.88) {
    return;
  }

  const morningShower = random() < 0.78;

  const minuteOfDay = morningShower
    ? randomInteger(random, 6 * 60 + person * 20, 8 * 60 + 30)
    : randomInteger(random, 18 * 60, 21 * 60);

  const totalGallons = randomBetween(random, 13, 19);

  addDistributedEvent(
    readings,
    day,
    minuteOfDay,
    2,
    totalGallons,
    "shower",
  );
}

function addToiletUses(
  readings: MutableReading[],
  day: number,
  random: () => number,
) {
  const uses = randomInteger(random, 3, 6);

  for (let i = 0; i < uses; i += 1) {
    const minuteOfDay = randomInteger(random, 6 * 60, 23 * 60);

    addDistributedEvent(
      readings,
      day,
      minuteOfDay,
      1,
      randomBetween(random, 1.15, 1.45),
      "toilet",
    );
  }
}

function addFaucetUses(
  readings: MutableReading[],
  day: number,
  random: () => number,
) {
  const uses = randomInteger(random, 4, 8);

  for (let i = 0; i < uses; i += 1) {
    const minuteOfDay = randomInteger(random, 6 * 60, 23 * 60);

    addDistributedEvent(
      readings,
      day,
      minuteOfDay,
      1,
      randomBetween(random, 0.15, 0.75),
      "faucet",
    );
  }
}

function addDishwasher(
  readings: MutableReading[],
  day: number,
  random: () => number,
) {
  const minuteOfDay = randomInteger(random, 19 * 60, 22 * 60);

  addDistributedEvent(
    readings,
    day,
    minuteOfDay,
    3,
    randomBetween(random, 3.2, 4.8),
    "dishwasher",
  );
}

function addWasher(
  readings: MutableReading[],
  day: number,
  random: () => number,
) {
  const minuteOfDay = randomInteger(random, 9 * 60, 19 * 60);

  addDistributedEvent(
    readings,
    day,
    minuteOfDay,
    4,
    randomBetween(random, 12, 18),
    "washer",
  );
}

function addNormalIrrigation(
  readings: MutableReading[],
  day: number,
  random: () => number,
) {
  const minuteOfDay = randomInteger(random, 5 * 60, 7 * 60);

  addDistributedEvent(
    readings,
    day,
    minuteOfDay,
    4,
    randomBetween(random, 18, 30),
    "irrigation",
  );
}

function addOvernightLeak(
  readings: MutableReading[],
  day: number,
) {
  const startMinute = 1 * 60 + 15;
  const endMinute = 6 * 60;

  const flowRateGpm = 0.14;
  const gallonsPerInterval = flowRateGpm * INTERVAL_MINUTES;

  for (
    let minute = startMinute;
    minute < endMinute;
    minute += INTERVAL_MINUTES
  ) {
    const index = getReadingIndex(day, minute);

    addUsage(
      readings,
      index,
      gallonsPerInterval,
      "leak",
      true,
      gallonsPerInterval,
    );
  }
}

function addRunningToilet(
  readings: MutableReading[],
  day: number,
  random: () => number,
) {
  for (
    let minute = 30;
    minute < 8 * 60;
    minute += random() < 0.5 ? 30 : 45
  ) {
    const index = getReadingIndex(day, minute);

    const excessGallons = randomBetween(random, 0.65, 1.1);

    addUsage(
      readings,
      index,
      excessGallons,
      "toilet",
      true,
      excessGallons,
    );
  }
}

function addIrrigationAfterRain(
  readings: MutableReading[],
  day: number,
) {
  const totalGallons = 28;
  const intervals = 4;
  const startMinute = 5 * 60 + 30;

  const gallonsPerInterval = totalGallons / intervals;

  for (let offset = 0; offset < intervals; offset += 1) {
    const minute = startMinute + offset * INTERVAL_MINUTES;
    const index = getReadingIndex(day, minute);

    addUsage(
      readings,
      index,
      gallonsPerInterval,
      "irrigation",
      true,
      gallonsPerInterval,
    );
  }
}

function addDistributedEvent(
  readings: MutableReading[],
  day: number,
  minuteOfDay: number,
  intervals: number,
  totalGallons: number,
  fixture: FixtureKind,
) {
  const gallonsPerInterval = totalGallons / intervals;

  for (let offset = 0; offset < intervals; offset += 1) {
    const minute =
      minuteOfDay + offset * INTERVAL_MINUTES;

    const index = getReadingIndex(day, minute);

    addUsage(
      readings,
      index,
      gallonsPerInterval,
      fixture,
    );
  }
}

function addUsage(
  readings: MutableReading[],
  index: number,
  gallons: number,
  fixture: FixtureKind,
  isAnomaly = false,
  excessGallons = 0,
) {
  const reading = readings[index];

  if (!reading) {
    return;
  }

  reading.gallons += gallons;
  reading.fixtures.add(fixture);

  if (isAnomaly) {
    reading.isAnomaly = true;
    reading.excessGallons += excessGallons;
  }
}

function finalizeReading(
  reading: MutableReading,
): MeterReading {
  return {
    timestamp: reading.timestamp,
    gallons: round(reading.gallons, 3),
    flowRateGpm: round(
      reading.gallons / INTERVAL_MINUTES,
      3,
    ),
    fixtures: [...reading.fixtures],
    isAnomaly: reading.isAnomaly,
    excessGallons: round(reading.excessGallons, 3),
  };
}

function calculateSummary(
  readings: MeterReading[],
) {
  const today = readings.slice(-INTERVALS_PER_DAY);
  const history = readings.slice(0, -INTERVALS_PER_DAY);

  const todayGallons = sum(
    today.map((reading) => reading.gallons),
  );

  const historicalDays =
    history.length / INTERVALS_PER_DAY;

  const historicalGallons = sum(
    history.map((reading) => reading.gallons),
  );

  const baselineDailyGallons =
    historicalDays > 0
      ? historicalGallons / historicalDays
      : 0;

  const anomalyReadings = today.filter(
    (reading) => reading.isAnomaly,
  );

  const firstAnomaly = anomalyReadings[0] ?? null;

  const excessGallons = sum(
    anomalyReadings.map(
      (reading) => reading.excessGallons,
    ),
  );

  const anomalyFlowRateGpm =
    anomalyReadings.length > 0
      ? Math.max(
          ...anomalyReadings.map(
            (reading) =>
              reading.excessGallons /
              INTERVAL_MINUTES,
          ),
        )
      : null;

  const differencePct =
    baselineDailyGallons > 0
      ? ((todayGallons - baselineDailyGallons) /
          baselineDailyGallons) *
        100
      : 0;

  return {
    todayGallons: round(todayGallons, 1),
    baselineDailyGallons: round(
      baselineDailyGallons,
      1,
    ),
    differencePct: round(differencePct, 1),
    anomalyDetected: anomalyReadings.length > 0,
    anomalyStart: firstAnomaly?.timestamp ?? null,
    excessGallons: round(excessGallons, 1),
    anomalyFlowRateGpm:
      anomalyFlowRateGpm === null
        ? null
        : round(anomalyFlowRateGpm, 2),
  };
}

function getReadingIndex(
  day: number,
  minuteOfDay: number,
) {
  const normalizedMinute = Math.min(
    Math.max(minuteOfDay, 0),
    24 * 60 - INTERVAL_MINUTES,
  );

  const slot = Math.floor(
    normalizedMinute / INTERVAL_MINUTES,
  );

  return day * INTERVALS_PER_DAY + slot;
}

function sum(values: number[]) {
  return values.reduce(
    (total, value) => total + value,
    0,
  );
}

function round(
  value: number,
  decimals: number,
) {
  const multiplier = 10 ** decimals;

  return (
    Math.round(
      (value + Number.EPSILON) * multiplier,
    ) / multiplier
  );
}

function randomBetween(
  random: () => number,
  min: number,
  max: number,
) {
  return min + random() * (max - min);
}

function randomInteger(
  random: () => number,
  min: number,
  max: number,
) {
  return Math.floor(
    randomBetween(random, min, max + 1),
  );
}

function createRandom(seed: number) {
  let state = seed >>> 0;

  return () => {
    state += 0x6d2b79f5;

    let value = state;

    value = Math.imul(
      value ^ (value >>> 15),
      value | 1,
    );

    value ^= value +
      Math.imul(
        value ^ (value >>> 7),
        value | 61,
      );

    return (
      ((value ^ (value >>> 14)) >>> 0) /
      4294967296
    );
  };
}