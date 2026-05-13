/**
 * Progress-stream types for the live agent timeline.
 *
 * Backend contract (see docs/superpowers/specs/2026-05-13-frontend-redesign-design.md §4):
 *   POST /extract/stream  → text/event-stream
 *   events: data: {"kind": "step", "step_id": "...", "state": "running", ...}
 *           data: {"kind": "cost", "cumulative_cost_usd": "0.1834"}
 *           data: {"kind": "period", "chunk_id": "period_03", "state": "danger"}
 *           data: {"kind": "result", "result": <ExtractResult>}
 *           data: {"kind": "done"}
 */

export type AgentState = "idle" | "running" | "done" | "error";

export interface AgentStepProgress {
  /** One of the LangGraph node ids — must match AGENT_STEPS[].id */
  step_id: string;
  state: AgentState;
  /** 0..1 — local progress within this step */
  progress: number;
  elapsed_ms: number;
  /** When the step fans out per period, count of parallel Sends */
  fanout?: number;
}

export type PeriodVisualState = "pending" | "running" | "success" | "danger";

export interface ExtractionProgress {
  thread_id: string;
  /** step_id currently active, "done" when finished */
  active_step: string;
  /** Cumulative LLM spend, USD — decimal string with 4dp (precision contract) */
  cumulative_cost_usd: string;
  steps: AgentStepProgress[];
  /** Per-chunk_id visual state — drives the period chip bar */
  period_states: Record<string, PeriodVisualState>;
}

/** Optional progress callback the API client invokes from SSE events. */
export type ProgressCallback = (p: ExtractionProgress) => void;
