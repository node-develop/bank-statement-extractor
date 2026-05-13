/**
 * Progress-stream types for the live agent timeline.
 *
 * MERGE INTO `frontend/src/types.ts` — do not import from this file,
 * copy these interfaces into your existing types module.
 *
 * Backend contract (Phase 5 — see PRD-redesign.md §5):
 *   GET /extract/stream/{thread_id}  → text/event-stream
 *   events: data: {"step_id": "...", "state": "running", ...}
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
