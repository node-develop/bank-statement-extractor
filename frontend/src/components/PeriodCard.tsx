import type React from "react";
import type { PeriodResult } from "../types";
import { ReconciliationBanner } from "./ReconciliationBanner";

interface Props {
  period: PeriodResult;
}

export function PeriodCard({ period }: Props) {
  const { account, summary, transactions, reconciliation } = period;

  return (
    <section
      style={{
        border: "1px solid #dee2e6",
        borderRadius: 6,
        padding: 16,
        marginBottom: 16,
      }}
    >
      <h2 style={{ margin: "0 0 8px 0", fontSize: "1rem", fontWeight: 700 }}>
        {account.bank} &mdash; ...{account.account_last4} &nbsp;
        <span style={{ fontWeight: 400, color: "#6c757d" }}>
          {account.period.start} &rarr; {account.period.end}
        </span>
      </h2>

      <ReconciliationBanner reconciliation={reconciliation} />

      <table
        style={{
          borderCollapse: "collapse",
          width: "100%",
          fontSize: "0.875rem",
          marginBottom: 12,
        }}
      >
        <tbody>
          <tr>
            <th style={thStyle}>Beginning balance</th>
            <td style={tdStyle}>${summary.beginning_balance}</td>
            <th style={thStyle}>Ending balance</th>
            <td style={tdStyle}>${summary.ending_balance}</td>
          </tr>
          <tr>
            <th style={thStyle}>Deposits total</th>
            <td style={tdStyle}>${summary.deposits_total}</td>
            <th style={thStyle}>Deposits count</th>
            <td style={tdStyle}>{summary.deposits_count}</td>
          </tr>
          <tr>
            <th style={thStyle}>Withdrawals total</th>
            <td style={tdStyle}>${summary.withdrawals_total}</td>
            <th style={thStyle}>Withdrawals count</th>
            <td style={tdStyle}>{summary.withdrawals_count}</td>
          </tr>
        </tbody>
      </table>

      <details>
        <summary
          style={{ cursor: "pointer", userSelect: "none", marginBottom: 8, fontWeight: 600 }}
        >
          Transactions ({transactions.length})
        </summary>
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              borderCollapse: "collapse",
              width: "100%",
              fontSize: "0.8125rem",
            }}
          >
            <thead>
              <tr>
                {["Date", "Description", "Direction", "Amount", "Balance"].map((h) => (
                  <th key={h} style={{ ...thStyle, background: "#f8f9fa" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {transactions.map((tx, i) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: transactions have no stable client-side key
                <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : "#f8f9fa" }}>
                  <td style={tdStyle}>{tx.date}</td>
                  <td style={{ ...tdStyle, maxWidth: 300, wordBreak: "break-word" }}>
                    {tx.description}
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      color: tx.direction === "credit" ? "#155724" : "#721c24",
                      fontWeight: 600,
                    }}
                  >
                    {tx.direction}
                  </td>
                  <td style={{ ...tdStyle, fontVariantNumeric: "tabular-nums" }}>${tx.amount}</td>
                  <td style={{ ...tdStyle, fontVariantNumeric: "tabular-nums" }}>
                    {tx.running_balance !== null ? `$${tx.running_balance}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "4px 8px",
  fontWeight: 600,
  whiteSpace: "nowrap",
  border: "1px solid #dee2e6",
  background: "#f8f9fa",
};

const tdStyle: React.CSSProperties = {
  padding: "4px 8px",
  border: "1px solid #dee2e6",
};
