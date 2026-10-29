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

  return <div className="grid items-start gap-8 py-6 xl:grid-cols-[minmax(0,1fr)_340px]">
    <HouseholdDashboard dataset={dataset} onScenarioChange={selectScenario} />
    <WaterAssistant scenarioId={dataset.scenario.id} />
  </div>;
}
