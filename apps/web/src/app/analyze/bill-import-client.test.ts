import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoClient, SessionExpired } from "../demo/demo-client";
import { encodeReport, MAX_REPORT_BYTES, parseImportedBill } from "../../lib/bill-import";

const token = "b".repeat(43);
const file = () => new File(["%PDF-1.7\nfictional water report"], "private-name.pdf", { type: "application/pdf" });
const result = () => ({ source: "document_import", needs_review: true,
  request_id: "12345678-abcd-1234-abcd-123456789abc", fields: {
    period_start: "2026-06-01", period_end_exclusive: "2026-07-01", usage: "8.5", usage_unit: "ccf",
    water_charge: "45.12", sewer_charge: null, currency: "USD",
  }, warnings: [] });
const session = () => Response.json({ session_token: token });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("report import", () => {
  it("requires consent and checks file size before any transmission", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    await expect(client.importBill(file(), false)).rejects.toThrow("Confirm sharing");
    await expect(client.importBill(new File([], "empty.pdf"), true)).rejects.toThrow("non-empty");
    await expect(client.importBill(new File([new Uint8Array(MAX_REPORT_BYTES + 1)], "big.pdf"), true)).rejects.toThrow("4 MiB");
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("sniffs actual content, rejecting mismatched extensions and unsupported photos", async () => {
    await expect(encodeReport(new File(["<script>bad</script>"], "bill.pdf", { type: "application/pdf" }))).rejects.toThrow("PDF, PNG");
    const encoded = await encodeReport(new File([new Uint8Array([255, 216, 255, 0])], "photo", { type: "" }));
    expect(encoded.media_type).toBe("image/jpeg");
    expect(atob(encoded.data_base64)).toHaveLength(4);
  });
  it("sends inline content without filename/cookies and returns nullable editable candidates", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(Response.json(result()));
    vi.stubGlobal("fetch", fetcher);
    const imported = await new DemoClient().importBill(file(), true);
    expect(imported.draft.sewer_charge).toBe("");
    expect(imported.draft.usage).toBe("8.5");
    const [url, options] = fetcher.mock.calls[1];
    expect(url).toBe("/api/aquamind/v1/bills/import");
    expect(options.credentials).toBe("omit"); expect(options.cache).toBe("no-store");
    expect(options.headers.Authorization).toBe(`Bearer ${token}`);
    expect(JSON.parse(options.body)).toEqual({ media_type: "application/pdf", share_with_ai: true,
      data_base64: btoa("%PDF-1.7\nfictional water report") });
    expect(options.body).not.toContain("private-name");
  });
  it("never retries an uncertain paid extraction and does not reveal server errors", async () => {
    for (const status of [401, 413, 422, 502, 503]) {
      const fetcher = vi.fn().mockResolvedValueOnce(session())
        .mockResolvedValueOnce(Response.json({ detail: "private details" }, { status }));
      vi.stubGlobal("fetch", fetcher);
      try { await new DemoClient().importBill(file(), true); throw new Error("unexpected success"); }
      catch (error) {
        expect((error as Error).message).not.toContain("private details");
        if (status === 401) expect(error).toBeInstanceOf(SessionExpired);
      }
      expect(fetcher).toHaveBeenCalledTimes(2);
    }
  });
  it("rejects overlapping operations on the same session", async () => {
    let release!: (value: Response) => void;
    const fetcher = vi.fn().mockReturnValueOnce(new Promise<Response>((resolve) => { release = resolve; }))
      .mockResolvedValueOnce(Response.json(result()));
    vi.stubGlobal("fetch", fetcher);
    const client = new DemoClient();
    const first = client.importBill(file(), true);
    await expect(client.importBill(file(), true)).rejects.toThrow("still running");
    release(session()); await first;
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("rejects unbounded text, private output fields, unsafe units and unknown warning text", () => {
    for (const value of [
      { ...result(), needs_review: false },
      { ...result(), warnings: ["private address"] },
      { ...result(), fields: { ...result().fields, account_number: "private" } },
      { ...result(), fields: { ...result().fields, usage_unit: "gallons" } },
      { ...result(), fields: { ...result().fields, usage: "x".repeat(1000) } },
    ]) expect(() => parseImportedBill(value)).toThrow("could not be read safely");
  });
});
