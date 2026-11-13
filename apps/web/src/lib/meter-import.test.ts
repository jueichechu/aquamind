import { afterEach, describe, expect, it, vi } from "vitest";
import { MeterClient, MeterError, parseMeterSummary, type MeterOptions } from "./meter-import";

const token = "m".repeat(43);
const options: MeterOptions = { volume_unit: "us_gallons", interval_minutes: 15, timezone: "UTC", reading_type: "actual" };
const file = () => new File(["interval_start,volume\n2026-06-01T00:00:00+00:00,15\n"], "readings.csv", { type: "text/csv" });
export const summaryFixture = () => ({ context: { evidence_id: "meter_example", household_id: "house_example", origin: "user_provided",
  dataset_sha256: "a".repeat(64), start: "2026-06-01T00:00:00Z", end_exclusive: "2026-06-01T00:15:00Z", reading_count: 1,
  interval_minutes: 15, volume_unit: "us_gallons", reading_type: "actual" }, timezone: "UTC", total_us_gallons: "15.000000",
  inference_status: "not_enabled_for_imported_data", limitations: ["Unverified user-provided readings."] });
afterEach(() => vi.unstubAllGlobals());

describe("meter boundary", () => {
  it("validates provenance, cadence, totals and real calendar instants before display", () => {
    expect(parseMeterSummary(summaryFixture()).context.origin).toBe("user_provided");
    const context = summaryFixture().context;
    for (const changes of [{ origin: "synthetic" }, { reading_count: true }, { volume_unit: "gpm" },
      { interval_minutes: 0 }, { household_id: "secret" }, { end_exclusive: "2026-06-01T00:30:00Z" },
      { start: "2026-02-31T00:00:00Z", end_exclusive: "2026-03-03T00:15:00Z" }]) {
      expect(() => parseMeterSummary({ ...summaryFixture(), context: { ...context, ...changes } })).toThrow();
    }
    for (const changes of [{ total_us_gallons: "NaN" }, { inference_status: "ready" }, { timezone: "Invalid/Zone" },
      { extra: "private" }, { total_us_gallons: "1000001.000000" }]) {
      expect(() => parseMeterSummary({ ...summaryFixture(), ...changes })).toThrow();
    }
  });

  it("requires local consent, file limits and explicit metadata before any network request", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const client = new MeterClient();
    await expect(client.importFile(file(), options, false)).rejects.toThrow("Confirm processing");
    await expect(client.importFile(new File(["x".repeat(65537)], "large.csv"), options, true)).rejects.toThrow("64 KiB");
    await expect(client.importFile(new File(["x"], "image.webp"), options, true)).rejects.toThrow(".csv");
    await expect(client.importFile(file(), { ...options, timezone: "" }, true)).rejects.toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("imports once with isolated bearer credentials, checks current data, clears and closes", async () => {
    const calls: { path: string; init: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (path, init) => {
      calls.push({ path, init });
      if (path.endsWith("/sessions")) return Response.json({ session_token: token });
      if (init.method === "DELETE") return new Response(null, { status: 204 });
      return Response.json(summaryFixture());
    }));
    const client = new MeterClient();
    await expect(client.importFile(file(), options, true)).resolves.toMatchObject({ total_us_gallons: "15.000000" });
    await client.current(); await client.clear(); client.close();
    expect(calls.map((item) => [item.path.split("/").at(-1), item.init.method])).toEqual([
      ["sessions", "POST"], ["import", "POST"], ["current", "GET"], ["current", "DELETE"], ["session", "DELETE"],
    ]);
    for (const call of calls) {
      expect(call.init.credentials).toBe("omit"); expect(call.init.cache).toBe("no-store");
      expect(call.path).not.toContain(token);
    }
    expect(calls[1].init.headers).toMatchObject({ Authorization: `Bearer ${token}` });
    expect(calls.at(-1)!.init.keepalive).toBe(true);
    const body = JSON.parse(calls[1].init.body as string);
    expect(body).toEqual({ ...options, consent_to_process: true, csv_text: await file().text() });
    expect(body).not.toHaveProperty("filename");
  });

  it("never retries uncertain writes or echoes upstream errors, and can read back explicitly", async () => {
    const fetcher = vi.fn(async (path: string) => path.endsWith("/sessions") ? Response.json({ session_token: token }) :
      new Response("PRIVATE_UPSTREAM_INPUT", { status: 503 }));
    vi.stubGlobal("fetch", fetcher);
    const client = new MeterClient();
    await expect(client.importFile(file(), options, true)).rejects.toMatchObject({ uncertain: true });
    expect(fetcher).toHaveBeenCalledTimes(2);
    fetcher.mockResolvedValue(Response.json(summaryFixture()));
    await expect(client.current()).resolves.toMatchObject({ total_us_gallons: "15.000000" });
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("handles expiry without silently creating a replacement session or replaying uploads", async () => {
    const fetcher = vi.fn(async (path: string) => path.endsWith("/sessions") ? Response.json({ session_token: token }) : new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetcher);
    const client = new MeterClient();
    await expect(client.importFile(file(), options, true)).rejects.toMatchObject({ expired: true });
    await expect(client.current()).rejects.toMatchObject({ expired: true });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("rejects mismatched metadata and malformed successes as unconfirmed", async () => {
    for (const response of [{ ...summaryFixture(), timezone: "America/New_York" }, { invalid: true }]) {
      vi.stubGlobal("fetch", vi.fn(async (path: string) => Response.json(path.endsWith("/sessions") ? { session_token: token } : response)));
      await expect(new MeterClient().importFile(file(), options, true)).rejects.toBeInstanceOf(MeterError);
    }
  });

  it("blocks double submission and revokes a session created after the workspace closes", async () => {
    let resolve!: (value: Response) => void;
    const session = new Promise<Response>((yes) => { resolve = yes; });
    const fetcher = vi.fn((path: string) => path.endsWith("/sessions") ? session : Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetcher);
    const client = new MeterClient();
    const first = client.importFile(file(), options, true);
    await expect(client.importFile(file(), options, true)).rejects.toThrow("still running");
    client.close(); resolve(Response.json({ session_token: token }));
    await expect(first).rejects.toThrow("closed");
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[1][0]).toBe("/api/aquamind/v1/session");
  });
});
