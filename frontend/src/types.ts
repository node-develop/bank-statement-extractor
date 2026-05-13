/**
 * TypeScript interfaces mirroring src/models/__init__.py.
 *
 * Precision contract: all monetary fields are JSON strings (e.g. "597068.70").
 * Do NOT parseFloat them. Display as-is, prefix "$" only in the UI layer.
 * Backend quantises to exactly 2 decimal places; the string form is canonical.
 *
 * Dates are ISO 8601 strings ("YYYY-MM-DD").
 */

export interface Period {
  start: string;
  end: string;
}

export interface Account {
  chunk_id: string;
  bank: string;
  account_last4: string;
  period: Period;
}

export interface Summary {
  chunk_id: string;
  /** Decimal string, e.g. "597068.70" */
  beginning_balance: string;
  /** Decimal string */
  ending_balance: string;
  /** Decimal string */
  deposits_total: string;
  deposits_count: number;
  /** Decimal string */
  withdrawals_total: string;
  withdrawals_count: number;
}

export interface Transaction {
  chunk_id: string;
  /** ISO 8601 date string */
  date: string;
  description: string;
  /** Decimal string, always >= 0; sign conveyed by direction */
  amount: string;
  direction: "credit" | "debit";
  /** Decimal string or null */
  running_balance: string | null;
}

export interface Reconciliation {
  chunk_id: string;
  reconciled: boolean;
  /** Decimal string — absolute delta between actual and computed ending balance */
  delta: string;
  notes: string[];
}

export interface PeriodResult {
  chunk_id: string;
  account: Account;
  summary: Summary;
  transactions: Transaction[];
  layout: string;
  reconciliation: Reconciliation;
}

export interface ExtractResult {
  periods: PeriodResult[];
  statement_sha256: string;
  langsmith_run_url: string | null;
  errors: string[];
}
