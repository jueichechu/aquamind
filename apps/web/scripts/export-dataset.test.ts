import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createMeterExperimentDataset } from "../src/lib/water/experiments";
import { exportMeterDataset } from "./export-dataset";

let directory: string;
beforeEach(() => { directory = mkdtempSync(join(tmpdir(), "aquamind-export-")); });
afterEach(() => { rmSync(directory, { recursive: true, force: true }); });

describe("dataset export", () => {
  it("exports the shared generator data with a verifiable checksum and stable bytes", () => {
    const args = ["--seed-start", "10", "--seed-count", "30"];
    const report = JSON.parse(exportMeterDataset([...args, "--output", "first.json"], directory));
    const first = readFileSync(report.output, "utf8");
    expect(JSON.parse(first)).toEqual(
      createMeterExperimentDataset(Array.from({ length: 30 }, (_, index) => index + 10)),
    );
    expect(report.sha256).toBe(createHash("sha256").update(first).digest("hex"));
    exportMeterDataset([...args, "--output", "second.json"], directory);
    expect(readFileSync(join(directory, "second.json"), "utf8")).toBe(first);
    for (const split of ["train", "validation", "test"]) {
      expect(report.windows[split]).toBe(JSON.parse(first)[split].length);
    }
  });

  it("creates parent directories and refuses to overwrite an existing artifact", () => {
    const args = ["--seed-count", "30"];
    const report = JSON.parse(exportMeterDataset(args, directory));
    const original = readFileSync(report.output, "utf8");
    expect(report.output).toBe(join(directory, "ml/data/generated/meter-experiment.json"));
    expect(() => exportMeterDataset(args, directory)).toThrow(/EEXIST/);
    expect(readFileSync(report.output, "utf8")).toBe(original);
  });

  it.each([
    ["--seed-count", "0"], ["--seed-count", "10001"], ["--seed-count", "1.5"],
    ["--seed-start", "-1"], ["--seed-start", "NaN"],
    ["--seed-start", "4294967295", "--seed-count", "2"],
    ["--seed-count", "1"], ["--output", ""], ["--unknown"], ["unexpected"],
  ])("rejects invalid arguments or empty splits before writing: %j", (...args) => {
    expect(() => exportMeterDataset(args, directory)).toThrow();
    expect(readdirSync(directory)).toEqual([]);
  });

  it("shows help without generating files", () => {
    expect(exportMeterDataset(["--help"], directory)).toContain("pnpm data:export");
    expect(readdirSync(directory)).toEqual([]);
  });
});
