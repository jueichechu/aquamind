import { BILL_UNITS, type BillDraft } from "./bills";

export const MAX_REPORT_BYTES = 4 * 1024 * 1024;
export const IMPORT_BODY_LIMIT = 4 * Math.ceil(MAX_REPORT_BYTES / 3) + 1024;
export const REPORT_ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp";
export const IMPORT_WARNINGS = {
  missing_dates: "Check the billing dates; some were missing or unclear.",
  missing_usage: "Check the total water usage; it was missing or unclear.",
  ambiguous_unit: "Choose the exact usage unit printed on your bill.",
  unsupported_currency: "Only USD charges are supported. Other or unclear charges were left blank.",
  multiple_bills: "This file appears to contain several bills. Select one bill or enter its values manually.",
  not_water_bill: "A water bill could not be identified. Choose a water bill or enter its values manually.",
  unclear_document: "Some details could not be read. Check every field against your report.",
} as const;
export type ImportedBill = { draft: BillDraft; warnings: (keyof typeof IMPORT_WARNINGS)[] };

export function checkReportSize(file: Pick<File, "size">) {
  if (file.size === 0 || file.size > MAX_REPORT_BYTES) throw new Error("Choose a non-empty report of up to 4 MiB.");
}

/** Read in memory only, after explicit sharing. The server checks the format again. */
export async function encodeReport(file: File) {
  checkReportSize(file);
  const bytes = new Uint8Array(await file.arrayBuffer());
  const starts = (signature: number[]) => signature.every((value, index) => bytes[index] === value);
  const media_type = starts([37, 80, 68, 70, 45]) ? "application/pdf" :
    starts([137, 80, 78, 71, 13, 10, 26, 10]) ? "image/png" :
    starts([255, 216, 255]) ? "image/jpeg" :
    starts([82, 73, 70, 70]) && String.fromCharCode(...bytes.slice(8, 12)) === "WEBP" ? "image/webp" : null;
  if (!media_type) throw new Error("Choose a PDF, PNG, JPEG or WebP report. Convert HEIC photos to JPEG first.");
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return { media_type, data_base64: btoa(binary), share_with_ai: true };
}

export function parseImportedBill(value: unknown): ImportedBill {
  const invalid = () => new Error("The report could not be read safely. Enter the values manually or choose another report.");
  if (!value || typeof value !== "object") throw invalid();
  const data = value as Record<string, unknown>;
  if (data.source !== "document_import" || data.needs_review !== true ||
      typeof data.request_id !== "string" || !/^[0-9a-f-]{36}$/.test(data.request_id) ||
      !data.fields || typeof data.fields !== "object" || Array.isArray(data.fields) ||
      !Array.isArray(data.warnings) || data.warnings.length > 7 ||
      data.warnings.some((warning) => typeof warning !== "string" || !Object.hasOwn(IMPORT_WARNINGS, warning))) throw invalid();
  const fields = data.fields as Record<string, unknown>;
  const patterns: Record<keyof BillDraft, RegExp> = {
    period_start: /^\d{4}-\d{2}-\d{2}$/, period_end_exclusive: /^\d{4}-\d{2}-\d{2}$/,
    usage: /^\d{1,9}(\.\d{1,6})?$/, usage_unit: new RegExp(`^(${Object.keys(BILL_UNITS).join("|")})$`),
    water_charge: /^\d{1,7}(\.\d{1,2})?$/, sewer_charge: /^\d{1,7}(\.\d{1,2})?$/, currency: /^USD$/,
  };
  if (Object.keys(fields).length !== Object.keys(patterns).length) throw invalid();
  const draft = {} as BillDraft;
  for (const key of Object.keys(patterns) as (keyof BillDraft)[]) {
    const field = fields[key];
    if (field !== null && (typeof field !== "string" || !patterns[key].test(field))) throw invalid();
    draft[key] = field === null ? "" : field as string;
  }
  return { draft, warnings: [...new Set(data.warnings)] as ImportedBill["warnings"] };
}
