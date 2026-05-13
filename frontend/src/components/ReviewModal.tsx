/**
 * ReviewModal — opens when ExtractResult.pending_review is non-null.
 *
 * Lets the user inspect each verifier suspect, edit the offending row's
 * fields inline, and submit corrections (or force-finalise the partial
 * result as-is).
 */

import { useEffect, useState } from "react";
import { ApiError, getReview, submitReview } from "../api";
import type { ExtractResult, PendingReview, Suspect, TransactionCorrection } from "../types";

interface Props {
  pending: PendingReview;
  onResolved: (result: ExtractResult) => void;
  onError: (message: string) => void;
}

const REASON_LABEL: Record<PendingReview["reason"], string> = {
  suspects_exceeded: "Too many verifier suspects (>3) on this statement.",
  cost_ceiling_exceeded: "LLM cost ceiling reached before extraction completed.",
  retry_exhausted: "Critic retries exhausted without resolution.",
};

interface SuspectEdit {
  /** Local form state per suspect — fields the user has typed. */
  fields: Record<string, string>;
  /** Whether to drop the row entirely. */
  shouldDelete: boolean;
}

export function ReviewModal({ pending, onResolved, onError }: Props): React.JSX.Element {
  const [suspects, setSuspects] = useState<Suspect[]>([]);
  const [edits, setEdits] = useState<Record<string, SuspectEdit>>({});
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getReview(pending.extraction_id)
      .then((data) => {
        if (cancelled) return;
        const list = (data.review_payload?.suspects ?? []) as Suspect[];
        setSuspects(list);
        setLoading(false);
      })
      .catch((err: unknown) => {
        const msg = err instanceof ApiError ? err.message : String(err);
        onError(msg);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pending.extraction_id, onError]);

  const suspectKey = (s: Suspect): string => `${s.chunk_id}:${s.row_index}`;

  function updateField(s: Suspect, field: string, value: string): void {
    setEdits((prev) => {
      const key = suspectKey(s);
      const existing = prev[key] ?? { fields: {}, shouldDelete: false };
      return {
        ...prev,
        [key]: {
          ...existing,
          fields: { ...existing.fields, [field]: value },
        },
      };
    });
  }

  function toggleDelete(s: Suspect): void {
    setEdits((prev) => {
      const key = suspectKey(s);
      const existing = prev[key] ?? { fields: {}, shouldDelete: false };
      return {
        ...prev,
        [key]: { ...existing, shouldDelete: !existing.shouldDelete },
      };
    });
  }

  function buildCorrections(): TransactionCorrection[] {
    const out: TransactionCorrection[] = [];
    for (const s of suspects) {
      const key = suspectKey(s);
      const edit = edits[key];
      if (edit === undefined) continue;
      if (edit.shouldDelete) {
        out.push({
          chunk_id: s.chunk_id,
          row_index: s.row_index,
          action: "delete",
          fields: {},
        });
        continue;
      }
      if (Object.keys(edit.fields).length > 0) {
        out.push({
          chunk_id: s.chunk_id,
          row_index: s.row_index,
          action: "edit",
          fields: edit.fields,
        });
      }
    }
    return out;
  }

  async function handleSubmit(force: boolean): Promise<void> {
    setSubmitting(true);
    try {
      const result = await submitReview(pending.extraction_id, {
        corrections: force ? [] : buildCorrections(),
        force,
      });
      onResolved(result);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : String(err);
      onError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      // biome-ignore lint/a11y/useSemanticElements: native <dialog> needs a showModal polyfill on older Safari; div + role=dialog + aria-modal is the documented fallback
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-modal-title"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.55)",
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        padding: 24,
        zIndex: 1000,
        overflowY: "auto",
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 8,
          width: "100%",
          maxWidth: 760,
          padding: 24,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        }}
      >
        <h2 id="review-modal-title" style={{ marginTop: 0, fontSize: "1.25rem", fontWeight: 700 }}>
          Human review required
        </h2>
        <p style={{ marginTop: 0, color: "#495057" }}>{REASON_LABEL[pending.reason]}</p>
        <p style={{ fontSize: "0.8125rem", color: "#6c757d" }}>
          extraction_id: <code>{pending.extraction_id}</code>
          <br />
          {pending.suspect_count} suspect{pending.suspect_count !== 1 ? "s" : ""} flagged.
        </p>

        {loading ? (
          <p>Loading suspects…</p>
        ) : suspects.length === 0 ? (
          <p style={{ color: "#6c757d" }}>No suspect details returned.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: "16px 0" }}>
            {suspects.map((s) => {
              const key = suspectKey(s);
              const edit = edits[key];
              return (
                <li
                  key={key}
                  style={{
                    border: "1px solid #dee2e6",
                    borderRadius: 4,
                    padding: 12,
                    marginBottom: 12,
                    background: edit?.shouldDelete ? "#fff3f3" : "#fff",
                  }}
                >
                  <div style={{ marginBottom: 8 }}>
                    <strong>{s.code}</strong> · {s.chunk_id} · row {s.row_index}
                  </div>
                  <div style={{ fontSize: "0.875rem", color: "#495057", marginBottom: 8 }}>
                    {s.reason}
                  </div>
                  {s.expected !== null && s.actual !== null && (
                    <div style={{ fontSize: "0.8125rem", color: "#6c757d", marginBottom: 8 }}>
                      expected <code>{s.expected}</code>, actual <code>{s.actual}</code>
                    </div>
                  )}

                  <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8 }}>
                    {(
                      ["date", "description", "amount", "direction", "running_balance"] as const
                    ).map((field) => (
                      <label key={field} style={{ display: "contents", fontSize: "0.8125rem" }}>
                        <span style={{ alignSelf: "center" }}>{field}</span>
                        <input
                          type="text"
                          value={edit?.fields?.[field] ?? ""}
                          onChange={(e) => {
                            updateField(s, field, e.target.value);
                          }}
                          placeholder={s.actual ?? ""}
                          disabled={edit?.shouldDelete ?? false}
                          style={{
                            padding: "4px 8px",
                            border: "1px solid #ced4da",
                            borderRadius: 3,
                            fontFamily: "ui-monospace, monospace",
                          }}
                        />
                      </label>
                    ))}
                  </div>

                  <label
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      marginTop: 8,
                      fontSize: "0.8125rem",
                      color: "#dc3545",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={edit?.shouldDelete ?? false}
                      onChange={() => {
                        toggleDelete(s);
                      }}
                    />
                    Delete this row instead
                  </label>
                </li>
              );
            })}
          </ul>
        )}

        <div style={{ display: "flex", gap: 12, justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={() => handleSubmit(true)}
            disabled={submitting}
            style={{
              padding: "8px 16px",
              border: "1px solid #6c757d",
              background: "#fff",
              color: "#6c757d",
              borderRadius: 4,
              cursor: submitting ? "not-allowed" : "pointer",
            }}
          >
            Force finalize
          </button>
          <button
            type="button"
            onClick={() => handleSubmit(false)}
            disabled={submitting || loading}
            style={{
              padding: "8px 16px",
              border: "1px solid #0d6efd",
              background: "#0d6efd",
              color: "#fff",
              borderRadius: 4,
              cursor: submitting ? "not-allowed" : "pointer",
            }}
          >
            {submitting ? "Submitting…" : "Apply & re-extract"}
          </button>
        </div>
      </div>
    </div>
  );
}
