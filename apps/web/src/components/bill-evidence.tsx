import type { BillEvidence, BillFieldSource } from "../lib/bill-import";

export function BillReadingNote({ evidence }: { evidence?: BillEvidence }) {
  const type = evidence?.reading_type ?? "unknown";
  const labels = {
    actual: "Bill marked as actual readings",
    estimated: "Bill marked as estimated readings",
    mixed: "Bill includes actual and estimated readings",
    unknown: "Reading type not identified",
  };
  const details = {
    actual: "This is an AI interpretation of the bill, not independent verification of your consumption.",
    estimated: "The billed usage may be estimated. Check the reading type before interpreting a change in consumption.",
    mixed: "Some readings may be estimated. Check which billing readings were measured before comparing consumption.",
    unknown: "Check your report for actual or estimated readings. The daily average alone cannot tell them apart.",
  };
  return <div className="text-sm leading-6">
    <p className={type === "estimated" || type === "mixed" ? "font-medium text-warning" : "font-medium text-ink"}>
      {labels[type]}{evidence?.reading_type_page ? ` (suggested page ${evidence.reading_type_page})` : ""}
    </p>
    <p className="mt-1 text-ink-secondary">{details[type]}</p>
  </div>;
}

export function BillSourceHint({ id, source, changed, empty, required, reviewed }: {
  id: string; source: BillFieldSource; changed: boolean; empty: boolean; required: boolean; reviewed: boolean;
}) {
  let text: string;
  let attention = false;
  if (required && empty) {
    text = `Enter this value from your report${!changed && source.page ? ` (suggested page ${source.page})` : ""}.`;
    attention = true;
  } else if (changed) {
    text = reviewed ? "Your edit, reviewed by you." : "Edited by you. Check against your report.";
  } else if (reviewed) {
    text = empty ? "Reviewed by you; left unknown." : "Reviewed by you. The extraction remains unverified.";
  } else if (source.kind === "unclear") {
    text = `Needs clarification${source.page ? ` (suggested page ${source.page})` : ""}. Check this value.`;
    attention = true;
  } else if (source.kind === "missing") {
    text = "Not found. Leave blank if unknown.";
  } else if (source.kind === "derived") {
    text = `Suggested exclusive end from page ${source.page}. Check the date conversion.`;
  } else {
    text = `Suggested source: page ${source.page}.`;
  }
  return <p id={id} className={`mt-2 text-xs leading-5 ${attention ? "text-warning" : "text-muted"}`}>{text}</p>;
}
