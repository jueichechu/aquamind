import type { ScenarioDefinition, ScenarioId } from "./types";

export const SCENARIOS: Record<ScenarioId, ScenarioDefinition> = {
  normal: {
    id: "normal",
    title: "Typical household day",
    description:
      "A normal household consumption pattern without a known anomaly.",
    status: "Normal",
    rainfallInchesLast24h: 0,
    temperatureF: 76,
  },

  "overnight-leak": {
    id: "overnight-leak",
    title: "Overnight continuous flow",
    description:
      "Steady water consumption appears overnight when household demand should be near zero.",
    status: "Attention",
    rainfallInchesLast24h: 0,
    temperatureF: 72,
  },

  "running-toilet": {
    id: "running-toilet",
    title: "Running toilet pattern",
    description:
      "Repeated refill events occur throughout periods with otherwise low household demand.",
    status: "Review",
    rainfallInchesLast24h: 0,
    temperatureF: 74,
  },

  "irrigation-after-rain": {
    id: "irrigation-after-rain",
    title: "Irrigation after rain",
    description:
      "Outdoor watering occurs despite substantial rainfall during the previous 24 hours.",
    status: "Opportunity",
    rainfallInchesLast24h: 0.68,
    temperatureF: 69,
  },
};