export interface HouseholdSeedSplit {
  train: number[];
  validation: number[];
  test: number[];
}

/** Split seed identities before generating scenario variants or overlapping windows. */
export function splitHouseholdSeeds(seeds: readonly number[]): HouseholdSeedSplit {
  for (const seed of seeds) {
    // The generator coerces seeds to uint32; reject aliases instead of splitting them apart.
    if (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) {
      throw new RangeError("Household seeds must be unsigned 32-bit integers");
    }
  }

  const split: HouseholdSeedSplit = { train: [], validation: [], test: [] };
  for (const seed of [...new Set(seeds)].sort((a, b) => a - b)) {
    const fraction = hashSeed(seed) / 0x100000000;
    if (fraction < 0.7) {
      split.train.push(seed);
    } else if (fraction < 0.85) {
      split.validation.push(seed);
    } else {
      split.test.push(seed);
    }
  }
  return split;
}

function hashSeed(seed: number): number {
  // Integer mixing avoids grouping nearby seeds; membership is independent of input order/size.
  let value = seed >>> 0;
  value = Math.imul(value ^ (value >>> 16), 0x7feb352d);
  value = Math.imul(value ^ (value >>> 15), 0x846ca68b);
  return (value ^ (value >>> 16)) >>> 0;
}
