/**
 * Static spec of the LangGraph node sequence. Drives the agent
 * timeline visualisation. `duration_ms` is a typical-run baseline
 * used for fallback animation only; once real SSE progress arrives,
 * widths are driven by `AgentStepProgress.progress` from the server.
 */

export interface AgentStepSpec {
  id: string;
  name: string;
  /** CSS var ref, e.g. "var(--agent-ingest)" */
  color: string;
  /** Runs once per (period_chunk_id) Send fan-out */
  runs_per_period: boolean;
  /** Baseline duration in ms — used only as a fallback when no SSE */
  duration_ms: number;
  /** Copy shown in the active-step indicator */
  desc: string;
}

export const AGENT_STEPS: AgentStepSpec[] = [
  { id: "ingest",                name: "ingest",                color: "var(--agent-ingest)",       runs_per_period: false, duration_ms: 800,  desc: "Reading PDF…" },
  { id: "split_periods",         name: "split_periods",         color: "var(--agent-split)",        runs_per_period: false, duration_ms: 200,  desc: "Splitting into periods…" },
  { id: "classify_layout",       name: "classify_layout",       color: "var(--agent-layout)",       runs_per_period: true,  duration_ms: 1800, desc: "Classifying layout…" },
  { id: "extract_account",       name: "extract_account",       color: "var(--agent-account)",      runs_per_period: true,  duration_ms: 1900, desc: "Extracting account metadata…" },
  { id: "extract_summary",       name: "extract_summary",       color: "var(--agent-summary)",      runs_per_period: true,  duration_ms: 2100, desc: "Extracting period summaries…" },
  { id: "extract_transactions",  name: "extract_transactions",  color: "var(--agent-transactions)", runs_per_period: true,  duration_ms: 4600, desc: "Extracting transactions…" },
  { id: "verifier",              name: "verifier",              color: "var(--agent-verifier)",     runs_per_period: false, duration_ms: 400,  desc: "Verifying chunks…" },
  { id: "reconcile",             name: "reconcile",             color: "var(--agent-reconcile)",    runs_per_period: false, duration_ms: 300,  desc: "Reconciling totals…" },
];

/** Formats decimal-string money as "$1,234.56" */
export function fmt$(s: string | number): string {
  const n = typeof s === "string" ? parseFloat(s) : s;
  if (Number.isNaN(n)) return "—";
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Shortform for hero stats — "$1.21M" style, here we just round + comma. */
export function fmt$short(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

/** Format a period's `Apr 2025` from a YYYY-MM-DD string. */
export function formatMonth(iso: string): string {
  const [y, m] = iso.split("-");
  const months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[parseInt(m, 10)]} ${y}`;
}
