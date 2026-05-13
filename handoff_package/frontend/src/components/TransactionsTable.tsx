import type { Transaction, Suspect } from "../types";
import { fmt$ } from "../lib/agentSteps";
import { IconAlert } from "./icons";

interface Props {
  transactions: Transaction[];
  /** Optional row→suspect map. Keyed by row index. */
  suspectsByRow?: Record<number, Suspect>;
}

export function TransactionsTable({ transactions, suspectsByRow }: Props) {
  return (
    <div className="tx-table-wrap">
      <table className="tx">
        <thead>
          <tr>
            <th style={{ width: 96 }}>Date</th>
            <th>Description</th>
            <th style={{ width: 90 }}>Direction</th>
            <th style={{ width: 120, textAlign: "right" }}>Amount</th>
            <th style={{ width: 130, textAlign: "right" }}>Balance</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((tx, i) => {
            const suspect = suspectsByRow?.[i];
            return (
              <tr key={i} className={suspect ? "suspect" : undefined}>
                <td className="tx-date">{tx.date}</td>
                <td>
                  {suspect && (
                    <span className="tx-suspect-pill" title={suspect.reason}>
                      <IconAlert size={9} /> {suspect.code}
                    </span>
                  )}
                  {tx.description}
                </td>
                <td>
                  <span className={tx.direction === "credit" ? "tx-dir-credit" : "tx-dir-debit"}>
                    <span
                      className="tx-dot"
                      style={{ background: tx.direction === "credit" ? "var(--success-fg)" : "var(--danger-fg)" }}
                    />
                    {tx.direction}
                  </span>
                </td>
                <td className="tx-num">{fmt$(tx.amount)}</td>
                <td className="tx-num">{tx.running_balance ? fmt$(tx.running_balance) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
