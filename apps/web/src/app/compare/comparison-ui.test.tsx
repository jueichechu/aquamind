import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import corpus from "../../../../../evals/fixtures/bill-comparison-contract-v1.json";
import { createBillComparisonEntries, parseBillComparisonResult } from "../../lib/bill-comparison";
import { ComparisonEntry } from "./comparison-entry";
import { ComparisonSummary, comparisonNumber } from "./comparison-summary";
import ComparePage from "./page";
import AnalyzePage from "../analyze/page";

it("renders empty repeated fields, unchecked required confirmation and an explicit submit without requests", () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  try {
    const html = renderToStaticMarkup(<ComparisonEntry />);
    expect(html).toContain('id="comparison-0-start"');
    expect(html).toContain('id="comparison-1-start"');
    expect(html).toContain('type="checkbox" required=""');
    expect(html).not.toMatch(/type="checkbox"[^>]*checked/);
    expect(html).toContain('aria-busy="false"');
    expect(html).toMatch(/<button[^>]*>Compare bills<\/button>/);
    expect(html).not.toContain("Remove bill");
    expect(html).toContain("does not use AI or save a bill history");
    expect(html).not.toContain("Your bill comparison");
    expect(fetcher).not.toHaveBeenCalled();
  } finally { vi.unstubAllGlobals(); }
});

it.each(corpus.cases)("renders validated results and accessible period rows: $name", ({ drafts, response }) => {
  const result = parseBillComparisonResult(response, createBillComparisonEntries(drafts));
  const html = renderToStaticMarkup(<ComparisonSummary result={result} example={false} />);
  expect(html).toContain('id="comparison-result-heading"');
  expect(html).toContain('tabindex="-1"');
  expect(html).toContain('href="#comparison-entry-heading"');
  expect(html).toContain("End dates are exclusive");
  expect(html.match(/scope="row"/g)).toHaveLength(result.bills.length);
  expect(html.match(/scope="col"/g)).toHaveLength(4);
  expect(html).toContain("assumed to describe the same household and meter");
  expect(html).toContain("No fixture diagnosis, cost trend or savings prediction");
  if (result.latest_percent_change === null) expect(html).toContain("Not defined: earlier usage is zero");
  else expect(html).toContain(`${comparisonNumber(result.latest_percent_change, true)}%`);
  if (result.gap_days > 0) expect(html).toContain(`${result.gap_days} days between supplied periods are excluded`);
});

it("preserves unknown versus zero charges and qualifies examples and rounded-zero baselines", () => {
  const fixture = corpus.cases[0];
  const result = parseBillComparisonResult(fixture.response, createBillComparisonEntries(fixture.drafts));
  const html = renderToStaticMarkup(<ComparisonSummary result={result} example />);
  expect(html).toContain("Example calculation; not your household data");
  expect(html).toContain("Sewer: Unknown");
  expect(html).toContain("Water: $0.00");
  expect(html).toContain("Subtotal: Unknown");
  expect(html).toContain("Subtotal: $0.00");
  const tiny = corpus.cases[2];
  expect(renderToStaticMarkup(<ComparisonSummary example={false}
    result={parseBillComparisonResult(tiny.response, createBillComparisonEntries(tiny.drafts))} />))
    .toContain("positive baseline rounds to zero");
  expect(comparisonNumber("-0.123456")).toBe("-0.123456");
  expect(comparisonNumber("138546071294399900.00", true)).toBe("138,546,071,294,399,900.00");
});

it("connects the comparison route from the existing analysis screen", () => {
  const compare = renderToStaticMarkup(<ComparePage />);
  expect(compare).toContain("Compare your water bills");
  expect(compare).toContain('href="/analyze"');
  expect(compare).toContain("water-desk");
  const analyze = renderToStaticMarkup(<AnalyzePage />);
  expect(analyze).toContain('href="/compare"');
  expect(analyze).toContain('href="/demo"');
  expect(analyze).toContain("Understand one water bill");
});
