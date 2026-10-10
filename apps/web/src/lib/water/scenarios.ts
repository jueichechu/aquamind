import weather from "./scenario-weather.json";
import type { ScenarioDefinition, ScenarioId } from "./types";

export const SCENARIOS: Record<ScenarioId, ScenarioDefinition> = {
  normal: {
    id: "normal",
    title: "Typical household day",
    description:
      "A normal household consumption pattern without a known anomaly.",
    status: "Normal",
    ...weather.scenarios["normal"],
  },

  "overnight-leak": {
    id: "overnight-leak",
    title: "Overnight continuous flow",
    description:
      "Steady water consumption appears overnight when household demand should be near zero.",
    status: "Attention",
    ...weather.scenarios["overnight-leak"],
  },

  "running-toilet": {
    id: "running-toilet",
    title: "Running toilet pattern",
    description:
      "Repeated refill events occur throughout periods with otherwise low household demand.",
    status: "Review",
    ...weather.scenarios["running-toilet"],
  },

  "irrigation-after-rain": {
    id: "irrigation-after-rain",
    title: "Irrigation after rain",
    description:
      "Outdoor watering occurs despite substantial rainfall during the previous 24 hours.",
    status: "Opportunity",
    ...weather.scenarios["irrigation-after-rain"],
  },
};