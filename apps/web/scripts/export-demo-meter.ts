import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { generateHouseholdDataset } from "../src/lib/water/generator";
import { SCENARIOS } from "../src/lib/water/scenarios";

/** Export measured gallons only; simulator labels and fixture identities stay out. */
export function demoMeterBytes(): string {
  return JSON.stringify({
    schema_version: 1,
    source: "synthetic",
    seed: 42,
    start_timestamp: generateHouseholdDataset("normal", 42).readings[0].timestamp,
    interval_minutes: 15,
    scenarios: Object.fromEntries(Object.values(SCENARIOS).map(({ id }) => [
      id, generateHouseholdDataset(id, 42).readings.map(({ gallons }) => gallons),
    ])),
  }) + "\n";
}

if (require.main === module) {
  const output = resolve(__dirname, "../../../../../ml/data/demo/meter-v1.json");
  const args = process.argv.slice(2);
  if (args.length === 1 && args[0] === "--check") {
    if (readFileSync(output, "utf8") !== demoMeterBytes()) {
      throw new Error("Demo meter snapshot differs from the simulator; regenerate with pnpm data:demo");
    }
    console.log("Demo meter snapshot matches the simulator");
  } else if (args.length === 0) {
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, demoMeterBytes());
    console.log("Exported ml/data/demo/meter-v1.json");
  } else {
    throw new Error("Usage: pnpm data:demo [--check]");
  }
}
