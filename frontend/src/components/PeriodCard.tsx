import { useMemo, useState } from "react";
import { fmt$, formatMonth } from "../lib/agentSteps";
import type { PeriodResult, Transaction } from "../types";
import { TransactionsTable } from "./TransactionsTable";
import { IconAlert, IconChevDown, IconCopy } from "./icons";
import { Button } from "./ui/Button";
import { Chip } from "./ui/Chip";
import { SectionLabel } from "./ui/SectionLabel";

interface Props {
  period: PeriodResult;
  initialOpen?: boolean;
  /** Real transactions array (period.transactions). Filtered/sliced before passing if needed. */
  transactions?: Transaction[];
  onReview?: (period: PeriodResult) => void;
}

export function PeriodCard({ period, initialOpen, transactions, onReview }: Props) {
  const [open, setOpen] = useState(!!initialOpen);
  const { account, summary, reconciliation, verifier } = period;
  const month = formatMonth(account.period.start);

  const suspectsByRow = useMemo(() => {
    const map: Record<number, NonNullable<typeof verifier>["suspects"][number]> = {};
    for (const s of verifier?.suspects ?? []) map[s.row_index] = s;
    return map;
  }, [verifier]);

  return (
    <section className={`period-card${open ? " open" : ""}`}>
      <div
        className="period-head"
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen(!open);
          }
        }}
        // biome-ignore lint/a11y/useSemanticElements: flex container as toggle; role + tabIndex + onKeyDown match button semantics without inheriting button styles
        role="button"
        tabIndex={0}
        aria-expanded={open}
      >
        <div style={{ flex: 1, display: "flex", alignItems: "baseline", gap: 4, flexWrap: "wrap" }}>
          <span className="period-title">
            {month}
            <span className="last4">· ...{account.account_last4}</span>
          </span>
          <span className="period-id">{period.chunk_id}</span>
        </div>
        {reconciliation.reconciled ? (
          <Chip kind="success" label="Reconciled" />
        ) : (
          <>
            <Chip kind="danger" label={`Δ ${fmt$(reconciliation.delta)}`} />
            <Button
              variant="danger-ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onReview?.(period);
              }}
              leftIcon={<IconAlert size={11} />}
            >
              Review
            </Button>
          </>
        )}
        <span className="chev">
          <IconChevDown size={16} />
        </span>
      </div>

      <div className="period-stats">
        <div>
          <div className="stat-label">Beginning</div>
          <div className="stat-value tnum mono">{fmt$(summary.beginning_balance)}</div>
        </div>
        <div>
          <div className="stat-label">Ending</div>
          <div className="stat-value tnum mono">{fmt$(summary.ending_balance)}</div>
        </div>
        <div>
          <div className="stat-label">Deposits</div>
          <div className="stat-value tnum mono">
            {fmt$(summary.deposits_total)}
            <span className="small">· {summary.deposits_count}</span>
          </div>
        </div>
        <div>
          <div className="stat-label">Withdrawals</div>
          <div className="stat-value tnum mono">
            {fmt$(summary.withdrawals_total)}
            <span className="small">· {summary.withdrawals_count}</span>
          </div>
        </div>
      </div>

      {open && transactions && transactions.length > 0 && (
        <div className="tx-wrap">
          <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
            <SectionLabel style={{ margin: 0 }}>{transactions.length} transactions</SectionLabel>
            <div style={{ flex: 1 }} />
            <Button variant="ghost" size="sm" leftIcon={<IconCopy size={11} />}>
              Copy as CSV
            </Button>
          </div>
          <TransactionsTable transactions={transactions} suspectsByRow={suspectsByRow} />
        </div>
      )}
    </section>
  );
}
