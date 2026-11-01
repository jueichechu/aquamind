import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import corpus from "../../../../../evals/fixtures/bill-import-review-v1.json";
import { DemoClient } from "../demo/demo-client";
import { createBillEntry, type BillDraft } from "../../lib/bills";
import { BillEntry } from "./bill-entry";

const token = "f".repeat(43);
const requestId = "12345678-abcd-1234-abcd-123456789abc";
// Format-signature probes only: mocked extraction does not decode a real document.
const probes: Record<string, number[]> = {
  "application/pdf": [37, 80, 68, 70, 45],
  "image/png": [137, 80, 78, 71, 13, 10, 26, 10],
  "image/jpeg": [255, 216, 255],
  "image/webp": [82, 73, 70, 70, 0, 0, 0, 0, 87, 69, 66, 80],
};
afterEach(() => vi.unstubAllGlobals());

it.each(corpus.cases)("preserves review and normalization contracts for $id", async (fixture) => {
  expect(corpus.synthetic).toBe(true);
  const fetcher = vi.fn().mockResolvedValueOnce(Response.json({ session_token: token }))
    .mockResolvedValueOnce(Response.json({ ...fixture.extraction, source: "document_import",
      needs_review: true, request_id: requestId }));
  vi.stubGlobal("fetch", fetcher);
  const client = new DemoClient();
  const file = new File([new Uint8Array(probes[fixture.media_type])], "private-report", { type: fixture.media_type });
  const imported = await client.importBill(file, true);
  expect(imported.evidence).toEqual(fixture.extraction.evidence);
  expect(imported.warnings).toEqual(fixture.extraction.warnings);
  expect(imported.draft).toEqual(Object.fromEntries(Object.entries(fixture.extraction.fields)
    .map(([key, value]) => [key, value ?? ""])));
  expect(JSON.parse(fetcher.mock.calls[1][1].body).media_type).toBe(fixture.media_type);
  expect(fetcher.mock.calls[1][1].body).not.toContain("private-report");

  const markup = renderToStaticMarkup(<BillEntry initialDraft={imported.draft} imported evidence={imported.evidence} />);
  expect(markup).toMatch(/<button[^>]*disabled=""[^>]*>Calculate bill usage<\/button>/);
  expect(markup).not.toMatch(/<input[^>]*type="checkbox"[^>]*checked/);
  expect(markup).toContain("unverified");
  if (Object.keys(fixture.review_edits).length || fixture.normalized === null) {
    await expect(client.normalizeBill(imported.draft)).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(2);
  }
  if (fixture.normalized !== null) {
    // These explicit edits simulate user correction, not automatic approval.
    const reviewed: BillDraft = { ...imported.draft, ...fixture.review_edits };
    const bill = createBillEntry(reviewed);
    fetcher.mockResolvedValueOnce(Response.json({ source: "manual_entry", evidence_level: "bill_only",
      confidence: "limited", request_id: requestId, bill, ...fixture.normalized }));
    const normalized = await client.normalizeBill(reviewed);
    expect(Object.fromEntries(Object.keys(fixture.normalized).map((key) =>
      [key, normalized[key as keyof typeof normalized]]))).toEqual(fixture.normalized);
    expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual(bill);
    expect(JSON.parse(fetcher.mock.calls[2][1].body)).not.toHaveProperty("evidence");
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/aquamind/v1/sessions", "/api/aquamind/v1/bills/import", "/api/aquamind/v1/bills/normalize",
    ]);
  }
});
