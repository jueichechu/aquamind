import { describe, expect, it } from "vitest";
import { splitHouseholdSeeds } from "./index";

const seeds = Array.from({ length: 1000 }, (_, seed) => seed);

describe("splitHouseholdSeeds", () => {
  it("assigns every unique seed to exactly one split", () => {
    const split = splitHouseholdSeeds([...seeds, ...seeds]);
    const assigned = [...split.train, ...split.validation, ...split.test];
    expect(assigned).toHaveLength(seeds.length);
    expect(new Set(assigned).size).toBe(seeds.length);
    expect(assigned.toSorted((a, b) => a - b)).toEqual(seeds);
  });

  it("is deterministic, order independent, and does not mutate its input", () => {
    const input = [...seeds].reverse();
    const original = [...input];
    expect(splitHouseholdSeeds(input)).toEqual(splitHouseholdSeeds(seeds));
    expect(splitHouseholdSeeds(input)).toEqual(splitHouseholdSeeds(input));
    expect(input).toEqual(original);
  });

  it("keeps existing assignments when the dataset grows", () => {
    const initial = splitHouseholdSeeds(seeds.slice(0, 100));
    const expanded = splitHouseholdSeeds(seeds);
    for (const name of ["train", "validation", "test"] as const) {
      expect(expanded[name].filter((seed) => seed < 100)).toEqual(initial[name]);
    }
  });

  it("provides approximately 70/15/15 proportions across many seeds", () => {
    const split = splitHouseholdSeeds(seeds);
    expect(split.train.length / seeds.length).toBeGreaterThan(0.65);
    expect(split.train.length / seeds.length).toBeLessThan(0.75);
    for (const group of [split.validation, split.test]) {
      expect(group.length / seeds.length).toBeGreaterThan(0.1);
      expect(group.length / seeds.length).toBeLessThan(0.2);
    }
  });

  it("handles empty input and uint32 boundaries", () => {
    expect(splitHouseholdSeeds([])).toEqual({ train: [], validation: [], test: [] });
    const split = splitHouseholdSeeds([0, 0xffffffff]);
    expect([...split.train, ...split.validation, ...split.test].toSorted((a, b) => a - b))
      .toEqual([0, 0xffffffff]);
  });

  it.each([-1, 0x100000000, 1.5, NaN, Infinity, -Infinity])(
    "rejects invalid seeds and generator aliases: %s", (seed) => {
      expect(() => splitHouseholdSeeds([42, seed])).toThrow(/unsigned 32-bit/);
    },
  );
});
