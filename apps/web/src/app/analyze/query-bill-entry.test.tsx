import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { QueryBillEntry } from "./query-bill-entry";

const state = vi.hoisted(() => ({ query: "" }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(state.query) }));

describe("bill entry query", () => {
  it("preserves the example link without requiring a request-time page server", () => {
    state.query = "example=1";
    const html = renderToStaticMarkup(<QueryBillEntry />);
    expect(html).toContain('value="8.5"');
    expect(html).toContain('value="2026-06-01"');
    expect(html).toContain("Example values; not your household data.");
  });

  it.each(["", "example=0", "example=untrusted"])("keeps ordinary entry empty for %s", (query) => {
    state.query = query;
    const html = renderToStaticMarkup(<QueryBillEntry />);
    expect(html).not.toContain('value="8.5"');
    expect(html).not.toContain('value="2026-06-01"');
  });
});
