import { Fragment, useState } from "react";
import type { PeriodResult, Suspect, TransactionCorrection } from "../types";
import { Button } from "./ui/Button";
import { Chip } from "./ui/Chip";
import { IconAlert, IconCheck, IconRefresh, IconXCircle } from "./icons";
import { fmt$ } from "../lib/agentSteps";

interface Props {
  period: PeriodResult;
  /** When provided, used as the source-of-truth suspect list. Otherwise reads period.verifier.suspects. */
  suspects?: Suspect[];
  /** True when a submission is in-flight. */
  busy?: boolean;
  onClose: () => void;
  onSubmit: (corrections: TransactionCorrection[], force: boolean) => void | Promise<void>;
}

interface EditEntry {
  fields: Record<string, string>;
  del: boolean;
}

const REASON_LABEL = {
  suspects_exceeded: "Too many verifier suspects in this period.",
  cost_ceiling_exceeded: "LLM cost ceiling reached before extraction completed.",
  retry_exhausted: "Critic retries exhausted without resolution.",
} as const;

export function ReviewModal({ period, suspects, busy, onClose, onSubmit }: Props) {
  const list = suspects ?? period.verifier?.suspects ?? [];
  const [edits, setEdits] = useState<Record<string, EditEntry>>({});

  const setField = (key: string, field: string, val: string) => {
    setEdits((p) => {
      const existing = p[key] ?? { fields: {}, del: false };
      return { ...p, [key]: { ...existing, fields: { ...existing.fields, [field]: val } } };
    });
  };
  const toggleDel = (key: string) => {
    setEdits((p) => {
      const existing = p[key] ?? { fields: {}, del: false };
      return { ...p, [key]: { ...existing, del: !existing.del } };
    });
  };

  function buildCorrections(): TransactionCorrection[] {
    const out: TransactionCorrection[] = [];
    for (const s of list) {
      const key = `${s.chunk_id}:${s.row_index}`;
      const e = edits[key];
      if (!e) continue;
      if (e.del) {
        out.push({ chunk_id: s.chunk_id, row_index: s.row_index, action: "delete", fields: {} });
        continue;
      }
      if (Object.keys(e.fields).length > 0) {
        out.push({ chunk_id: s.chunk_id, row_index: s.row_index, action: "edit", fields: e.fields });
      }
    }
    return out;
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 32, height: 32, borderRadius: 999,
              background: "var(--warning-bg)", border: "1px solid var(--warning-border)",
              color: "var(--warning-fg)",
              display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}>
              <IconAlert size={16} />
            </div>
            <div style={{ flex: 1 }}>
              <h2 className="t-h4" style={{ margin: 0 }}>Human review required</h2>
              <div className="t-caption" style={{ marginTop: 2 }}>
                {REASON_LABEL.suspects_exceeded} {period.chunk_id}
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={onClose} leftIcon={<IconXCircle size={13} />}>Close</Button>
          </div>
          <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 12, display: "flex", gap: 14, flexWrap: "wrap" }}>
            <span>{list.length} suspects flagged</span>
            <span>·</span>
            <span>delta: {fmt$(period.reconciliation.delta)}</span>
          </div>
        </div>

        <div className="modal-body">
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 12 }}>
            {list.map((s) => {
              const key = `${s.chunk_id}:${s.row_index}`;
              const e = edits[key];
              return (
                <li
                  key={key}
                  style={{
                    border: "1px solid " + (e?.del ? "var(--danger-border)" : "var(--border-1)"),
                    background: e?.del ? "var(--danger-bg)" : "#fff",
                    borderRadius: "var(--radius-3)",
                    padding: 14,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                    <Chip kind="warning" label={s.code.replace(/_/g, " ")} />
                    <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>
                      {s.chunk_id} · row {s.row_index}
                    </span>
                  </div>
                  <div className="t-small" style={{ color: "var(--ink-2)", marginBottom: 10 }}>
                    {s.reason}
                  </div>
                  {s.expected && s.actual && (
                    <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", marginBottom: 12 }}>
                      expected <span style={{ color: "var(--success-fg)" }}>{s.expected}</span>{" · "}
                      actual <span style={{ color: "var(--danger-fg)" }}>{s.actual}</span>
                    </div>
                  )}

                  <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto 1fr", gap: 8, alignItems: "center" }}>
                    {(["date", "description", "amount", "direction"] as const).map((field) => (
                      <Fragment key={field}>
                        <label className="t-label-muted" style={{ alignSelf: "center", color: "var(--ink-3)" }}>
                          {field}
                        </label>
                        <input
                          className="mono"
                          value={e?.fields?.[field] ?? ""}
                          onChange={(ev) => setField(key, field, ev.target.value)}
                          placeholder={field === "amount" ? s.actual ?? "" : field === "date" ? "YYYY-MM-DD" : ""}
                          disabled={e?.del}
                          style={{
                            font: "inherit", fontSize: 12,
                            padding: "5px 8px",
                            border: "1px solid var(--border-2)",
                            borderRadius: 4,
                            background: e?.del ? "var(--surface-2)" : "#fff",
                          }}
                        />
                      </Fragment>
                    ))}
                  </div>
                  <label style={{ display: "inline-flex", alignItems: "center", gap: 6, marginTop: 10, fontSize: 12, color: "var(--danger-fg)", cursor: "pointer" }}>
                    <input type="checkbox" checked={!!e?.del} onChange={() => toggleDel(key)} />
                    Delete this row instead
                  </label>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="modal-foot">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="secondary" disabled={busy} onClick={() => onSubmit([], true)} leftIcon={<IconCheck size={13} />}>
            Force finalize
          </Button>
          <Button variant="primary" disabled={busy} onClick={() => onSubmit(buildCorrections(), false)} leftIcon={<IconRefresh size={13} />}>
            {busy ? "Submitting…" : "Apply & re-extract"}
          </Button>
        </div>
      </div>
    </div>
  );
}
