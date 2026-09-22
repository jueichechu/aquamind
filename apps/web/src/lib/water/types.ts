export type FixtureKind =
  | "baseline"
  | "toilet"
  | "shower"
  | "faucet"
  | "dishwasher"
  | "washer"
  | "irrigation"
  | "leak";

export type ScenarioId =
  | "normal"
  | "overnight-leak"
  | "running-toilet"
  | "irrigation-after-rain";

export interface MeterReading {
  timestamp: string;
  gallons: number;
  flowRateGpm: number;
  fixtures: FixtureKind[];
  isAnomaly: boolean;
  excessGallons: number;
}

export interface ScenarioDefinition {
  id: ScenarioId;
  title: string;
  description: string;
  status: "Normal" | "Attention" | "Review" | "Opportunity";
  rainfallInchesLast24h: number;
  temperatureF: number;
}

export interface HouseholdSummary {
  todayGallons: number;
  baselineDailyGallons: number;
  differencePct: number;
  anomalyDetected: boolean;
  anomalyStart: string | null;
  excessGallons: number;
  anomalyFlowRateGpm: number | null;
}

export interface HouseholdDataset {
  scenario: ScenarioDefinition;
  readings: MeterReading[];
  summary: HouseholdSummary;
}