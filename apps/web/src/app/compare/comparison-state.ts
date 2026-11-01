import type { BillDraft } from "../../lib/bills";
import type { BillComparisonResult } from "../../lib/bill-comparison";

const empty: BillDraft = { period_start: "", period_end_exclusive: "", usage: "", usage_unit: "",
  water_charge: "", sewer_charge: "", currency: "" };
const examples: BillDraft[] = [
  { ...empty, period_start: "2026-02-01", period_end_exclusive: "2026-03-01", usage: "2800", usage_unit: "us_gallons" },
  { ...empty, period_start: "2026-03-01", period_end_exclusive: "2026-04-01", usage: "3100", usage_unit: "us_gallons" },
];
export type ComparisonState = {
  items: { id: number; draft: BillDraft }[];
  nextId: number;
  example: boolean;
  sameHousehold: boolean;
  busy: boolean;
  result: BillComparisonResult | null;
  error: string;
};
type Action = { type: "edit"; id: number; field: keyof BillDraft; value: string }
  | { type: "add" } | { type: "remove"; id: number } | { type: "replace"; example: boolean }
  | { type: "confirm"; value: boolean } | { type: "start" }
  | { type: "success"; result: BillComparisonResult } | { type: "failure"; message: string };

export function initialComparisonState(example = false): ComparisonState {
  return { items: (example ? examples : [empty, empty]).map((draft, id) => ({ id, draft: { ...draft } })),
    nextId: 2, example, sameHousehold: false, busy: false, result: null, error: "" };
}

export function comparisonReducer(state: ComparisonState, action: Action): ComparisonState {
  if (state.busy && action.type !== "success" && action.type !== "failure") return state;
  const changed = { ...state, sameHousehold: false, result: null, error: "" };
  switch (action.type) {
    case "edit":
      return { ...changed, items: state.items.map((item) => item.id === action.id ?
        { ...item, draft: { ...item.draft, [action.field]: action.value } } : item) };
    case "add":
      return state.items.length >= 12 ? state : { ...changed, nextId: state.nextId + 1,
        items: [...state.items, { id: state.nextId, draft: { ...empty } }] };
    case "remove":
      return state.items.length <= 2 ? state : { ...changed, items: state.items.filter((item) => item.id !== action.id) };
    case "replace": return initialComparisonState(action.example);
    case "confirm": return { ...state, sameHousehold: action.value, result: null, error: "" };
    case "start":
      return state.sameHousehold ? { ...state, busy: true, result: null, error: "" } :
        { ...state, result: null, error: "Confirm that these bills describe the same household and meter." };
    case "success": return state.busy ? { ...state, busy: false, result: action.result, error: "" } : state;
    case "failure": return { ...state, busy: false, result: null, error: action.message };
  }
}
