"use client";

import { useState } from "react";
import { generateHouseholdDataset, type HouseholdDataset, type ScenarioId } from "@/lib/water";
import { HouseholdDashboard } from "./household-dashboard";
import { WaterAssistant } from "./water-assistant";

export function DemoWorkspace({ initialDataset }: { initialDataset: HouseholdDataset }) {
  const [dataset, setDataset] = useState(initialDataset);

  function selectScenario(scenarioId: ScenarioId) {
    setDataset(generateHouseholdDataset(scenarioId));
  }

  return <div className="grid gap-4 py-4 lg:grid-cols-[240px_minmax(0,1fr)_360px]">
    <HouseholdDashboard dataset={dataset} onScenarioChange={selectScenario} />
    <WaterAssistant scenarioId={dataset.scenario.id} />
  </div>;
}
