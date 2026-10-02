import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { parseArgs } from "node:util";
import { createMeterExperimentDataset } from "../src/lib/water/experiments";

const HELP = `Export synthetic AquaMind meter sequences for model experiments.
Usage: pnpm data:export [--seed-start 0] [--seed-count 1000] [--output PATH]
Paths are relative to the repository root. Existing files are never overwritten.
Default output: ml/data/generated/meter-experiment.json
Seed count: 1–10000; seed range must fit unsigned 32-bit integers.`;

function integerOption(value: string, name: string, min: number, max: number) {
  if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)) ||
      Number(value) < min || Number(value) > max) {
    throw new RangeError(`${name} must be an integer from ${min} to ${max}`);
  }
  return Number(value);
}

export function exportMeterDataset(args: string[], repositoryRoot: string): string {
  const { values } = parseArgs({
    args,
    options: {
      "seed-start": { type: "string", default: "0" },
      "seed-count": { type: "string", default: "1000" },
      output: { type: "string", default: "ml/data/generated/meter-experiment.json" },
      help: { type: "boolean", default: false },
    },
    strict: true,
    allowPositionals: false,
  });
  if (values.help) return HELP;
  const start = integerOption(values["seed-start"]!, "seed-start", 0, 0xffffffff);
  const count = integerOption(values["seed-count"]!, "seed-count", 1, 10000);
  if (start + count - 1 > 0xffffffff) {
    throw new RangeError("Seed range must fit unsigned 32-bit integers");
  }
  if (!values.output?.trim()) throw new Error("output must be a non-empty path");

  const dataset = createMeterExperimentDataset(
    Array.from({ length: count }, (_, index) => start + index),
  );
  for (const split of ["train", "validation", "test"] as const) {
    if (dataset[split].length === 0) {
      throw new Error(`Empty ${split} split; choose a larger seed range`);
    }
  }

  const contents = JSON.stringify(dataset) + "\n";
  const output = resolve(repositoryRoot, values.output);
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, contents, { encoding: "utf8", flag: "wx" });
  return JSON.stringify({
    output,
    source: dataset.source,
    sha256: createHash("sha256").update(contents).digest("hex"),
    windows: {
      train: dataset.train.length,
      validation: dataset.validation.length,
      test: dataset.test.length,
    },
  }, null, 2);
}

if (require.main === module) {
  try {
    // Compiled entry point: apps/web/out/dataset/scripts/export-dataset.js.
    console.log(exportMeterDataset(process.argv.slice(2), resolve(__dirname, "../../../../..")));
  } catch (error) {
    console.error(error instanceof Error ? error.message : "Dataset export failed");
    process.exitCode = 1;
  }
}
