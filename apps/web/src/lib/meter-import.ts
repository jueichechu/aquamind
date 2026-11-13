import { BILL_UNITS } from "./bills";

export const METER_CSV_LIMIT = 64 * 1024;
export type MeterOptions = { volume_unit: keyof typeof BILL_UNITS; interval_minutes: number;
  timezone: string; reading_type: "actual" | "estimated" | "mixed" | "unknown" };
export type MeterSummary = { context: { evidence_id: string; household_id: string; origin: "user_provided";
  dataset_sha256: string; start: string; end_exclusive: string; reading_count: number;
  interval_minutes: number; volume_unit: keyof typeof BILL_UNITS; reading_type: MeterOptions["reading_type"] };
  timezone: string; total_us_gallons: string; inference_status: "not_enabled_for_imported_data"; limitations: string[] };
export class MeterError extends Error {
  constructor(message: string, readonly uncertain = false, readonly expired = false) { super(message); }
}
const invalid = () => new MeterError("The selected readings could not be confirmed. Check the current selection before importing again.", true);
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const id = (value: unknown) => typeof value === "string" && /^[a-z][a-z0-9_-]{7,63}$/.test(value);
const exact = (object: Record<string, unknown>, keys: string[]) => Object.keys(object).length === keys.length && keys.every((key) => Object.hasOwn(object, key));

export function validateMeterOptions(options: MeterOptions) {
  if (!Object.hasOwn(BILL_UNITS, options.volume_unit) || !Number.isInteger(options.interval_minutes) ||
      options.interval_minutes < 1 || options.interval_minutes > 60 ||
      !["actual", "estimated", "mixed", "unknown"].includes(options.reading_type) ||
      typeof options.timezone !== "string" || !options.timezone || options.timezone.length > 64) {
    throw new MeterError("Choose a volume unit, cadence, reading type and IANA timezone.");
  }
  try { new Intl.DateTimeFormat("en-US", { timeZone: options.timezone }); }
  catch { throw new MeterError("Enter a supported IANA timezone, such as America/Los_Angeles or UTC."); }
}

export function parseMeterSummary(value: unknown): MeterSummary {
  if (!record(value) || !exact(value, ["context", "timezone", "total_us_gallons", "inference_status", "limitations"]) ||
      !record(value.context)) throw invalid();
  const context = value.context;
  if (!exact(context, ["evidence_id", "household_id", "origin", "dataset_sha256", "start", "end_exclusive",
      "interval_minutes", "reading_count", "volume_unit", "reading_type"]) || !id(context.evidence_id) || !id(context.household_id) ||
      context.origin !== "user_provided" || typeof context.dataset_sha256 !== "string" || !/^[a-f0-9]{64}$/.test(context.dataset_sha256) ||
      typeof context.start !== "string" || typeof context.end_exclusive !== "string" ||
      ![context.start, context.end_exclusive].every((time) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00(?:Z|\+00:00)$/.test(time) && Number.isFinite(Date.parse(time)) && new Date(time).toISOString() === time.replace(/\+00:00$/, "Z").replace(/Z$/, ".000Z")) ||
      typeof context.reading_count !== "number" || !Number.isInteger(context.reading_count) || context.reading_count < 1 || context.reading_count > 672 ||
      typeof context.interval_minutes !== "number" || Date.parse(context.end_exclusive) - Date.parse(context.start) !== context.reading_count * context.interval_minutes * 60000 ||
      typeof value.total_us_gallons !== "string" || !/^\d{1,7}\.\d{6}$/.test(value.total_us_gallons) || Number(value.total_us_gallons) > 1000000 ||
      value.inference_status !== "not_enabled_for_imported_data" || !Array.isArray(value.limitations) || value.limitations.length > 8 ||
      !value.limitations.every((text) => typeof text === "string" && text.length <= 400)) throw invalid();
  const result = value as unknown as MeterSummary;
  try { validateMeterOptions({ ...result.context, timezone: result.timezone }); } catch { throw invalid(); }
  return result;
}

export function checkMeterFile(file: File) {
  if (!file.name.toLowerCase().endsWith(".csv") || file.size < 1 || file.size > METER_CSV_LIMIT) {
    throw new MeterError("Choose a nonempty .csv file up to 64 KiB.");
  }
}

/** One mounted workspace, RAM only; no retries, browser storage, cookies or model calls. */
export class MeterClient {
  #token: string | null = null;
  #busy = false;
  #version = 0;

  async #request(path: string, method: string, body?: object, token = this.#token): Promise<Response> {
    let response: Response;
    try {
      response = await fetch(`/api/aquamind/v1/${path}`, { method, credentials: "omit", cache: "no-store",
        keepalive: method === "DELETE" && path === "session",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(20000) });
    } catch { throw new MeterError("The request could not be confirmed. Check the current selection; it will not be retried automatically.", true); }
    if (response.status === 401) {
      if (token === this.#token) this.#token = null;
      throw new MeterError("Your meter session ended. Choose your CSV and consent again to start a new import.", false, true);
    }
    if (response.status === 404) throw new MeterError("Meter import is not enabled on this deployment. Bill calculations are still available.");
    if (response.status === 422) throw new MeterError("Check the CSV columns, volumes, timezone offsets and cadence. Readings must be ordered with no gaps or duplicates.");
    if (response.status === 413) throw new MeterError("The import is too large. Choose a CSV up to 64 KiB and 672 readings.");
    if (response.status === 429) throw new MeterError("The service is busy. Wait before making another request.");
    if (!response.ok) throw invalid();
    return response;
  }

  async #perform<T>(operation: () => Promise<T>, create = false): Promise<T> {
    if (this.#busy) throw new MeterError("Another meter request is still running.");
    this.#busy = true;
    const version = this.#version;
    try {
      if (!this.#token && create) {
        const response = await this.#request("sessions", "POST", {});
        const session = await response.json().catch(() => { throw invalid(); });
        if (!record(session) || typeof session.session_token !== "string" || !/^[A-Za-z0-9_-]{40,128}$/.test(session.session_token)) throw invalid();
        if (version !== this.#version) {
          void this.#request("session", "DELETE", undefined, session.session_token).catch(() => {});
          throw new MeterError("The meter workspace was closed.");
        }
        this.#token = session.session_token;
      }
      if (!this.#token) throw new MeterError("No active meter session. Choose your CSV and consent to import it.", false, true);
      const result = await operation();
      if (version !== this.#version) throw new MeterError("The meter workspace was closed.");
      return result;
    } finally { this.#busy = false; }
  }

  importFile(file: File, options: MeterOptions, consent: boolean) {
    try { checkMeterFile(file); validateMeterOptions(options);
      if (consent !== true) throw new MeterError("Confirm processing these readings before importing.");
    } catch (error) { return Promise.reject(error); }
    return this.#perform(async () => {
      const bytes = await file.arrayBuffer();
      if (bytes.byteLength < 1 || bytes.byteLength > METER_CSV_LIMIT) throw new MeterError("Choose a nonempty CSV up to 64 KiB.");
      let csv: string;
      try { csv = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
      catch { throw new MeterError("Save your CSV as UTF-8 text and choose it again."); }
      const body = { ...options, csv_text: csv, consent_to_process: true };
      if (new TextEncoder().encode(JSON.stringify(body)).byteLength > 96 * 1024) throw new MeterError("The encoded import is too large. Choose a smaller CSV.");
      const response = await this.#request("meters/import", "POST", body);
      const summary = parseMeterSummary(await response.json().catch(() => { throw invalid(); }));
      if (summary.timezone !== options.timezone || summary.context.interval_minutes !== options.interval_minutes ||
          summary.context.volume_unit !== options.volume_unit || summary.context.reading_type !== options.reading_type) throw invalid();
      return summary;
    }, true);
  }
  current() {
    return this.#perform(async () => {
      const response = await this.#request("meters/current", "GET");
      const value = await response.json().catch(() => { throw invalid(); });
      return value === null ? null : parseMeterSummary(value);
    });
  }
  clear() {
    return this.#perform(async () => {
      const response = await this.#request("meters/current", "DELETE");
      if (response.status !== 204) throw invalid();
    });
  }
  close() {
    const token = this.#token;
    this.#token = null; this.#version++;
    if (token) void this.#request("session", "DELETE", undefined, token).catch(() => {});
  }
}
