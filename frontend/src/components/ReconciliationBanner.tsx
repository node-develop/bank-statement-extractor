import type { Reconciliation } from "../types";

interface Props {
  reconciliation: Reconciliation;
}

export function ReconciliationBanner({ reconciliation }: Props) {
  if (reconciliation.reconciled) {
    return (
      <output
        style={{
          display: "block",
          background: "#d4edda",
          border: "1px solid #28a745",
          borderRadius: 4,
          padding: "8px 12px",
          marginBottom: 8,
          color: "#155724",
          fontWeight: 600,
        }}
      >
        Reconciled
      </output>
    );
  }

  return (
    <div
      role="alert"
      style={{
        background: "#f8d7da",
        border: "2px solid #dc3545",
        borderRadius: 4,
        padding: "10px 14px",
        marginBottom: 8,
        color: "#721c24",
      }}
    >
      <strong>Not reconciled.</strong> Delta: ${reconciliation.delta}
      {reconciliation.notes.length > 0 && (
        <ul style={{ margin: "6px 0 0 0", paddingLeft: 20 }}>
          {reconciliation.notes.slice(0, 3).map((note, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: notes have no stable key
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
