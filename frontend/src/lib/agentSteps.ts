/**
 * Static spec of the LangGraph node sequence + money formatting helpers.
 *
 * `AGENT_STEPS` is the **happy-path** 8-lane list shown in the live timeline.
 * Side-graph nodes — `merge_state`, `critic`, `apply_critic_hint`,
 * `await_review`, `finalize` — are NOT in this list. The processing view
 * shows them via a secondary "Side step" indicator driven off SSE events
 * tagged `side: true`.
 *
 * Money helpers use BigInt cents internally (no parseFloat) per the
 * precision contract in `src/types.ts`.
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
  {
    id: "ingest",
    name: "ingest",
    color: "var(--agent-ingest)",
    runs_per_period: false,
    duration_ms: 800,
    desc: "Reading PDF…",
  },
  {
    id: "split_periods",
    name: "split_periods",
    color: "var(--agent-split)",
    runs_per_period: false,
    duration_ms: 200,
    desc: "Splitting into periods…",
  },
  {
    id: "classify_layout",
    name: "classify_layout",
    color: "var(--agent-layout)",
    runs_per_period: true,
    duration_ms: 1800,
    desc: "Classifying layout…",
  },
  {
    id: "extract_account",
    name: "extract_account",
    color: "var(--agent-account)",
    runs_per_period: true,
    duration_ms: 1900,
    desc: "Extracting account metadata…",
  },
  {
    id: "extract_summary",
    name: "extract_summary",
    color: "var(--agent-summary)",
    runs_per_period: true,
    duration_ms: 2100,
    desc: "Extracting period summaries…",
  },
  {
    id: "extract_transactions",
    name: "extract_transactions",
    color: "var(--agent-transactions)",
    runs_per_period: true,
    duration_ms: 4600,
    desc: "Extracting transactions…",
  },
  {
    id: "verifier",
    name: "verifier",
    color: "var(--agent-verifier)",
    runs_per_period: false,
    duration_ms: 400,
    desc: "Verifying chunks…",
  },
  {
    id: "reconcile",
    name: "reconcile",
    color: "var(--agent-reconcile)",
    runs_per_period: false,
    duration_ms: 300,
    desc: "Reconciling totals…",
  },
];

/**
 * Parse a decimal money string ("597068.70" / "100.5" / "100" / "-12.34")
 * into BigInt cents (59706870n). Throws on malformed input.
 */
export function centsFromDecimalString(s: string): bigint {
  const m = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(s.trim());
  if (m === null) throw new Error(`fmt$: malformed money string "${s}"`);
  const sign = m[1];
  const whole = m[2];
  const frac = `${m[3] ?? ""}00`;
  return BigInt(sign + whole + frac.slice(0, 2));
}

/** Format BigInt cents as "$1,234.56" (or "-$12.34"). */
export function formatCents(cents: bigint): string {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const whole = abs / 100n;
  const c = (abs % 100n).toString().padStart(2, "0");
  const wholeStr = whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${(negative ? "-$" : "$") + wholeStr}.${c}`;
}

/** Display helper: Decimal string → "$1,234.56". Returns "—" on malformed input. */
export function fmt$(s: string | null | undefined): string {
  if (typeof s !== "string") return "—";
  try {
    return formatCents(centsFromDecimalString(s));
  } catch {
    return "—";
  }
}

/** Shortform for hero stats — "$1,234" (no cents). Decimal string input only (precision contract). */
export function fmt$short(s: string): string {
  try {
    const cents = centsFromDecimalString(s);
    const dollars = cents / 100n;
    return `$${dollars.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`;
  } catch {
    return "—";
  }
}

/**
 * Sum a list of decimal money strings using BigInt-cents arithmetic.
 * Returns the result as a normalised decimal string with exactly 2 dp.
 * Malformed inputs are skipped (caller may log).
 */
export function sumMoney(parts: Array<string | null | undefined>): string {
  let total = 0n;
  for (const s of parts) {
    if (typeof s !== "string") continue;
    try {
      total += centsFromDecimalString(s);
    } catch {
      // Skip malformed entries silently — total stays accurate over good entries.
    }
  }
  const negative = total < 0n;
  const abs = negative ? -total : total;
  const whole = abs / 100n;
  const c = (abs % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${whole}.${c}`;
}

/** Format a period's `Apr 2025` from a YYYY-MM-DD string. */
export function formatMonth(iso: string): string {
  const [y, m] = iso.split("-");
  const months = [
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  return `${months[Number.parseInt(m, 10)]} ${y}`;
}
