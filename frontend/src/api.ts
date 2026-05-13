/**
 * API client for POST /extract.
 *
 * All HTTP is centralised here; components never call fetch directly.
 * VITE_API_BASE is read from import.meta.env with a fallback to the
 * default local backend origin.
 */

import { AGENT_STEPS } from "./lib/agentSteps";
import type { ExtractResult, TransactionCorrection } from "./types";
import type {
  AgentStepProgress,
  ExtractionProgress,
  PeriodVisualState,
  ProgressCallback,
} from "./types-progress";

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

/**
 * GET the full payload of a paused extraction (suspects + chunk excerpts).
 * The first read transitions the row to status='in_review'.
 */
export async function getReview(extractionId: string): Promise<{
  extraction_id: string;
  status: string;
  reason: string | null;
  review_payload: { suspects: unknown[]; reason: string };
  statement_sha256: string;
}> {
  const response = await fetch(`${API_BASE}/review/${extractionId}`);
  const text = await response.text();
  if (!response.ok) {
    throw buildApiError(response.status, text);
  }
  return JSON.parse(text);
}

/**
 * POST corrections to resume a paused extraction.
 * @param extractionId — uuid from ExtractResult.pending_review.
 * @param payload — corrections list + force flag (force=true bypasses re-extraction).
 */
export async function submitReview(
  extractionId: string,
  payload: { corrections: TransactionCorrection[]; force: boolean },
): Promise<ExtractResult> {
  const response = await fetch(`${API_BASE}/review/${extractionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const text = await response.text();
  if (!response.ok) {
    throw buildApiError(response.status, text);
  }
  return JSON.parse(text) as ExtractResult;
}

// ---------------------------------------------------------------------------
// SSE streaming variant (Phase 6) — POST /extract/stream
// ---------------------------------------------------------------------------

type StreamEvent =
  | {
      kind: "step";
      step_id: string;
      state: "running" | "done" | "error";
      progress: number;
      elapsed_ms: number;
      fanout?: number;
      side?: boolean;
    }
  | { kind: "cost"; cumulative_cost_usd: string }
  | { kind: "period"; chunk_id: string; state: PeriodVisualState }
  | { kind: "result"; result: ExtractResult }
  | { kind: "done" }
  | { kind: "error"; message: string };

function emptyProgress(): ExtractionProgress {
  return {
    thread_id: "",
    active_step: AGENT_STEPS[0].id,
    cumulative_cost_usd: "0.0000",
    steps: AGENT_STEPS.map((s) => ({
      step_id: s.id,
      state: "idle",
      progress: 0,
      elapsed_ms: 0,
    })),
    period_states: {},
  };
}

function parseSseEvent(raw: string): StreamEvent | null {
  if (!raw.startsWith("data:")) return null;
  const json = raw.slice(5).trim();
  if (json === "") return null;
  try {
    const obj = JSON.parse(json) as { kind?: unknown };
    if (typeof obj.kind !== "string") {
      console.warn("parseSseEvent: missing 'kind'", json);
      return null;
    }
    return obj as StreamEvent;
  } catch (err) {
    console.warn("parseSseEvent: invalid JSON", json, err);
    return null;
  }
}

function fold(prev: ExtractionProgress, ev: StreamEvent): ExtractionProgress {
  if (ev.kind === "step") {
    if (ev.side === true) {
      return {
        ...prev,
        active_step: ev.state === "running" ? ev.step_id : prev.active_step,
      };
    }
    const idx = prev.steps.findIndex((s) => s.step_id === ev.step_id);
    if (idx < 0) return prev;
    const updated: AgentStepProgress = {
      step_id: ev.step_id,
      state: ev.state,
      progress: ev.progress,
      elapsed_ms: ev.elapsed_ms,
      fanout: ev.fanout,
    };
    const steps = prev.steps.slice();
    steps[idx] = updated;
    return {
      ...prev,
      steps,
      active_step: ev.state === "running" ? ev.step_id : prev.active_step,
    };
  }
  if (ev.kind === "cost") {
    return { ...prev, cumulative_cost_usd: ev.cumulative_cost_usd };
  }
  if (ev.kind === "period") {
    return {
      ...prev,
      period_states: { ...prev.period_states, [ev.chunk_id]: ev.state },
    };
  }
  return prev;
}

/**
 * POST multipart to /extract/stream, parse SSE, accumulate progress.
 *
 * - On 404, falls back to the JSON /extract endpoint (graceful degradation
 *   when the backend hasn't shipped Phase 4 yet — log only).
 * - Calls onProgress on every accumulator update.
 * - Returns when a kind:"result" event arrives, or throws ApiError on
 *   protocol violation / kind:"error".
 * - signal lets the caller AbortController-cancel the underlying fetch.
 */
export async function extractStatementStreaming(
  pdfFile: File,
  ocrFile?: File,
  onProgress?: ProgressCallback,
  signal?: AbortSignal,
): Promise<ExtractResult> {
  const form = new FormData();
  form.append("file", pdfFile);
  if (ocrFile !== undefined) {
    form.append("ocr_text", ocrFile);
  }

  const response = await fetch(`${API_BASE}/extract/stream`, {
    method: "POST",
    body: form,
    signal,
  });

  if (response.status === 404) {
    console.warn("extractStatementStreaming: /extract/stream not found — falling back to /extract");
    return extractStatement(pdfFile, ocrFile);
  }
  if (!response.ok) {
    const text = await response.text();
    throw buildApiError(response.status, text);
  }
  if (response.body === null) {
    throw new ApiError(500, "No response body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  let progress = emptyProgress();
  if (onProgress) onProgress(progress);

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx = buf.indexOf("\n\n");
      while (idx !== -1) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const ev = parseSseEvent(raw);
        if (ev !== null) {
          if (ev.kind === "result") {
            return ev.result;
          }
          if (ev.kind === "done") {
            throw new ApiError(500, "SSE stream ended without a result event");
          }
          if (ev.kind === "error") {
            throw new ApiError(500, ev.message);
          }
          progress = fold(progress, ev);
          if (onProgress) onProgress(progress);
        }
        idx = buf.indexOf("\n\n");
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // ignore — stream may already be released on abort
    }
  }
  throw new ApiError(500, "SSE stream closed before a result event");
}
