import { describe, expect, it } from "vitest";
import corpus from "../../../../../evals/fixtures/bill-comparison-contract-v1.json";
import { createBillComparisonEntries, parseBillComparisonResult } from "../../lib/bill-comparison";
import { comparisonReducer as reduce, initialComparisonState } from "./comparison-state";

const fixture = corpus.cases[0];
const result = parseBillComparisonResult(fixture.response, createBillComparisonEntries(fixture.drafts));
function calculated() {
  let state = initialComparisonState(true);
  state = reduce(state, { type: "confirm", value: true });
  state = reduce(state, { type: "start" });
  return reduce(state, { type: "success", result });
}

describe("comparison entry transitions", () => {
  it("starts with two independent empty drafts and no implied household confirmation", () => {
    const state = initialComparisonState();
    expect(state.items).toHaveLength(2);
    expect(state.sameHousehold).toBe(false);
    expect(state.result).toBeNull();
    expect(state.example).toBe(false);
    const edited = reduce(state, { type: "edit", id: 0, field: "usage", value: "9" });
    expect(edited.items[0].draft.usage).toBe("9");
    expect(edited.items[1].draft.usage).toBe("");
    expect(state.items[0].draft.usage).toBe("");
  });

  it("requires confirmation before starting and clears it whenever entries change", () => {
    expect(reduce(initialComparisonState(), { type: "start" })).toMatchObject({ busy: false, result: null });
    expect(reduce(initialComparisonState(), { type: "start" }).error).toContain("same household");
    for (const action of [{ type: "edit", id: 0, field: "usage", value: "1" }, { type: "add" },
      { type: "confirm", value: false }, { type: "replace", example: false }] as const) {
      const changed = reduce(calculated(), action);
      expect(changed.result).toBeNull();
      expect(changed.sameHousehold).toBe(false);
    }
  });

  it("bounds the list and preserves stable IDs and neighboring values on removal", () => {
    let state = initialComparisonState(true);
    state = reduce(state, { type: "add" });
    state = reduce(state, { type: "edit", id: 2, field: "usage", value: "123" });
    state = reduce(state, { type: "confirm", value: true });
    state = reduce(state, { type: "remove", id: 1 });
    expect(state.items.map((item) => item.id)).toEqual([0, 2]);
    expect(state.items[1].draft.usage).toBe("123");
    expect(state.sameHousehold).toBe(false);
    expect(reduce(state, { type: "remove", id: 0 })).toBe(state);
    while (state.items.length < 12) state = reduce(state, { type: "add" });
    expect(reduce(state, { type: "add" })).toBe(state);
    expect(new Set(state.items.map((item) => item.id)).size).toBe(12);
  });

  it("ignores every entry mutation during a request and replaces stale results only on success", () => {
    const ready = calculated();
    const running = reduce(ready, { type: "start" });
    expect(running.busy).toBe(true);
    expect(running.result).toBeNull();
    for (const action of [{ type: "edit", id: 0, field: "usage", value: "999" }, { type: "add" },
      { type: "remove", id: 0 }, { type: "replace", example: false }, { type: "confirm", value: false },
      { type: "start" }] as const) expect(reduce(running, action)).toBe(running);
    const completed = reduce(running, { type: "success", result });
    expect(completed.result).toBe(result);
    expect(completed.busy).toBe(false);
    expect(reduce(initialComparisonState(), { type: "success", result }).result).toBeNull();
  });

  it("clears results after failure and retains example provenance until an explicit clear", () => {
    const failed = reduce(reduce(calculated(), { type: "start" }), { type: "failure", message: "Session expired" });
    expect(failed).toMatchObject({ busy: false, result: null, error: "Session expired", example: true });
    const edited = reduce(failed, { type: "edit", id: 0, field: "usage", value: "1" });
    expect(edited.example).toBe(true);
    expect(edited.error).toBe("");
    const cleared = reduce(edited, { type: "replace", example: false });
    expect(cleared).toEqual(initialComparisonState());
    expect(reduce(cleared, { type: "replace", example: true }).items[0].draft.usage).toBe("2800");
  });
});
