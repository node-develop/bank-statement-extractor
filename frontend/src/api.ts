/**
 * API client for POST /extract.
 *
 * All HTTP is centralised here; components never call fetch directly.
 * VITE_API_BASE is read from import.meta.env with a fallback to the
 * default local backend origin.
 */

import type { ExtractResult } from "./types";

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/** Typed error thrown for non-2xx responses from the API. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function buildApiError(status: number, body: string): ApiError {
  let message: string;
  try {
    const parsed = JSON.parse(body) as Record<string, unknown>;
    const detail = parsed.detail;
    if (typeof detail === "string") {
      message = detail;
    } else if (typeof parsed.error === "string") {
      message = parsed.error;
    } else {
      message = body;
    }
  } catch {
    message = body || `HTTP ${status}`;
  }
  return new ApiError(status, message);
}

/**
 * POST multipart form to /extract.
 *
 * @param pdfFile  - Required bank-statement PDF (≤ 25 MB).
 * @param ocrFile  - Optional companion OCR text file (≤ 5 MB).
 * @throws {ApiError} on any non-2xx response.
 */
export async function extractStatement(pdfFile: File, ocrFile?: File): Promise<ExtractResult> {
  const form = new FormData();
  form.append("file", pdfFile);
  if (ocrFile !== undefined) {
    form.append("ocr_text", ocrFile);
  }

  const response = await fetch(`${API_BASE}/extract`, {
    method: "POST",
    body: form,
  });

  const text = await response.text();

  if (!response.ok) {
    throw buildApiError(response.status, text);
  }

  return JSON.parse(text) as ExtractResult;
}
