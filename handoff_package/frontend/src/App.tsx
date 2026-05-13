import { useCallback, useState } from "react";
import type { ExtractResult, PeriodResult } from "./types";
import type { ExtractionProgress, ProgressCallback } from "./types-progress";
import { Header } from "./components/Header";
import { UploadView } from "./components/UploadView";
import { ProcessingView } from "./components/ProcessingView";
import { ResultsView } from "./components/ResultsView";
import { ReviewModal } from "./components/ReviewModal";
import { AGENT_STEPS, formatMonth } from "./lib/agentSteps";
import { ApiError, extractStatement, submitReview } from "./api";

type Phase = "upload" | "processing" | "results";

/** Initial progress shape, before any SSE event has arrived. */
function emptyProgress(): ExtractionProgress {
  return {
    thread_id: "",
    active_step: AGENT_STEPS[0].id,
    cumulative_cost_usd: 0,
    steps: AGENT_STEPS.map((s) => ({ step_id: s.id, state: "idle", progress: 0, elapsed_ms: 0 })),
    period_states: {},
  };
}

export default function App() {
  const [phase, setPhase] = useState<Phase>("upload");
  const [progress, setProgress] = useState<ExtractionProgress>(emptyProgress());
  const [result, setResult] = useState<ExtractResult | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<PeriodResult | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onProgress: ProgressCallback = useCallback((p) => setProgress(p), []);

  async function handleSubmit(pdf: File, ocr: File | null) {
    setError(null);
    setFilename(pdf.name);
    setProgress(emptyProgress());
    setPhase("processing");
    try {
      const r = await extractStatement(pdf, ocr ?? undefined, onProgress);
      setResult(r); setPhase("results");
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Network error — is the API running?";
      setError(msg); setPhase("upload");
    }
  }

  async function handleReviewSubmit(corrections: Parameters<typeof submitReview>[1]["corrections"], force: boolean) {
    if (!result?.pending_review) return;
    setSubmitBusy(true);
    try {
      const r = await submitReview(result.pending_review.extraction_id, { corrections, force });
      setResult(r);
      setReviewing(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSubmitBusy(false);
    }
  }

  return (
    <div className="bse-root app-shell">
      <Header
        subtitle={phase !== "upload" ? filename : null}
        cost={phase === "processing" ? progress.cumulative_cost_usd : (phase === "results" ? progress.cumulative_cost_usd || undefined : null)}
        showReset={phase !== "upload"}
        onReset={() => { setPhase("upload"); setResult(null); setReviewing(null); setError(null); }}
      />
      <main className="app-main">
        {phase === "upload" && (
          <UploadView onSubmit={handleSubmit} />
        )}
        {phase === "processing" && (
          <ProcessingView
            progress={progress}
            periods={[]/* fill in once split_periods event arrives */}
            onCancel={() => setPhase("upload")}
          />
        )}
        {phase === "results" && result && (
          <ResultsView
            result={result}
            filename={filename ?? undefined}
            wallClockText={undefined}
            costUsd={progress.cumulative_cost_usd || undefined}
            onReview={setReviewing}
          />
        )}
        {error && (
          <div role="alert" style={{
            maxWidth: 720, margin: "16px auto",
            background: "var(--danger-bg)",
            border: "1px solid var(--danger-border)",
            borderRadius: "var(--radius-3)",
            padding: "10px 14px",
            color: "var(--danger-fg)",
          }}>
            {error}
          </div>
        )}
      </main>

      {reviewing && (
        <ReviewModal
          period={reviewing}
          busy={submitBusy}
          onClose={() => setReviewing(null)}
          onSubmit={handleReviewSubmit}
        />
      )}
    </div>
  );
}
