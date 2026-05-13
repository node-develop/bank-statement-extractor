import { useState } from "react";
import { PeriodCard } from "./components/PeriodCard";
import { ReviewModal } from "./components/ReviewModal";
import { UploadForm } from "./components/UploadForm";
import type { ExtractResult } from "./types";

export default function App() {
  const [result, setResult] = useState<ExtractResult | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const hasUnreconciled = result?.periods.some((p) => !p.reconciliation.reconciled);
  const pendingReview = result?.pending_review ?? null;

  return (
    <div
      style={{
        maxWidth: 960,
        margin: "0 auto",
        padding: "24px 16px",
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        lineHeight: 1.5,
        color: "#212529",
      }}
    >
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: 20 }}>
        Bank Statement Analyzer
      </h1>

      <UploadForm onResult={setResult} />

      {pendingReview !== null && (
        <ReviewModal
          pending={pendingReview}
          onResolved={(r) => {
            setResult(r);
            setReviewError(null);
          }}
          onError={setReviewError}
        />
      )}

      {reviewError !== null && (
        <div
          role="alert"
          style={{
            background: "#f8d7da",
            border: "1px solid #dc3545",
            borderRadius: 4,
            padding: "10px 14px",
            marginBottom: 16,
            color: "#721c24",
          }}
        >
          Review submission failed: {reviewError}
        </div>
      )}

      {result !== null && (
        <>
          {hasUnreconciled && (
            <div
              role="alert"
              style={{
                background: "#f8d7da",
                border: "2px solid #dc3545",
                borderRadius: 4,
                padding: "12px 16px",
                marginBottom: 20,
                color: "#721c24",
                fontWeight: 700,
                fontSize: "1rem",
              }}
            >
              One or more periods did not reconcile. See the red banners below.
            </div>
          )}

          {result.errors.length > 0 && (
            <div
              role="alert"
              style={{
                background: "#fff3cd",
                border: "1px solid #ffc107",
                borderRadius: 4,
                padding: "10px 14px",
                marginBottom: 20,
                color: "#856404",
              }}
            >
              <strong>Pipeline warnings ({result.errors.length}):</strong>
              <ul style={{ margin: "6px 0 0 0", paddingLeft: 20 }}>
                {result.errors.map((e, i) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: errors have no stable key
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}

          <div style={{ marginBottom: 12, fontSize: "0.8125rem", color: "#6c757d" }}>
            SHA-256: {result.statement_sha256}
            {result.langsmith_run_url !== null && (
              <>
                {" · "}
                <a
                  href={result.langsmith_run_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "#0d6efd" }}
                >
                  LangSmith trace
                </a>
              </>
            )}
          </div>

          <p style={{ marginBottom: 16, fontSize: "0.875rem", color: "#495057" }}>
            {result.periods.length} period{result.periods.length !== 1 ? "s" : ""} extracted.
          </p>

          {result.periods.map((period) => (
            <PeriodCard key={period.chunk_id} period={period} />
          ))}

          <details style={{ marginTop: 32 }}>
            <summary
              style={{ cursor: "pointer", fontWeight: 600, userSelect: "none", marginBottom: 8 }}
            >
              Raw JSON response
            </summary>
            <pre
              style={{
                background: "#f8f9fa",
                border: "1px solid #dee2e6",
                borderRadius: 4,
                padding: 16,
                overflowX: "auto",
                fontSize: "0.8125rem",
                maxHeight: 600,
                overflowY: "auto",
              }}
            >
              {JSON.stringify(result, null, 2)}
            </pre>
          </details>
        </>
      )}
    </div>
  );
}
