import { useCallback, useRef, useState } from "react";
import { ApiError, extractStatementStreaming, submitReview } from "./api";
import { Header } from "./components/Header";
import { ProcessingView } from "./components/ProcessingView";
import { ResultsView } from "./components/ResultsView";
import { ReviewModal } from "./components/ReviewModal";
import { UploadView } from "./components/UploadView";
import { AGENT_STEPS } from "./lib/agentSteps";
import type { ExtractResult, PeriodResult } from "./types";
import type { ExtractionProgress, ProgressCallback } from "./types-progress";

type Phase = "upload" | "processing" | "results";

/** Initial progress shape, before any SSE event has arrived. */
function emptyProgress(): ExtractionProgress {
  return {
    thread_id: "",
    active_step: AGENT_STEPS[0].id,
    cumulative_cost_usd: "0.0000",
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

  const abortRef = useRef<AbortController | null>(null);

  const onProgress: ProgressCallback = useCallback((p) => setProgress(p), []);

  async function handleSubmit(pdf: File, ocr: File | null) {
    setError(null);
    setFilename(pdf.name);
    setProgress(emptyProgress());
    setPhase("processing");
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const r = await extractStatementStreaming(
        pdf,
        ocr ?? undefined,
        onProgress,
        controller.signal,
      );
      setResult(r);
      setPhase("results");
    } catch (e) {
      if (controller.signal.aborted) {
        setPhase("upload");
        return;
      }
      const msg = e instanceof ApiError ? e.message : "Network error — is the API running?";
      setError(msg);
      setPhase("upload");
    }
  }

  async function handleReviewSubmit(
    corrections: Parameters<typeof submitReview>[1]["corrections"],
    force: boolean,
  ) {
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
        cost={phase !== "upload" ? progress.cumulative_cost_usd : null}
        showReset={phase !== "upload"}
        onReset={() => {
          setPhase("upload");
          setResult(null);
          setReviewing(null);
          setError(null);
        }}
      />
      <main className="app-main">
        {phase === "upload" && <UploadView onSubmit={handleSubmit} />}
        {phase === "processing" && (
          <ProcessingView
            progress={progress}
            periods={Object.keys(progress.period_states).map((id) => ({
              id,
              month: "Unknown",
              last4: "",
            }))}
            onCancel={() => abortRef.current?.abort()}
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
          <div
            role="alert"
            style={{
              maxWidth: 720,
              margin: "16px auto",
              background: "var(--danger-bg)",
              border: "1px solid var(--danger-border)",
              borderRadius: "var(--radius-3)",
              padding: "10px 14px",
              color: "var(--danger-fg)",
            }}
          >
            {error}
          </div>
        )}
      </main>

      {reviewing && (
        <ReviewModal
          period={reviewing}
          pauseReason={result?.pending_review?.reason ?? "suspects_exceeded"}
          busy={submitBusy}
          onClose={() => setReviewing(null)}
          onSubmit={handleReviewSubmit}
        />
      )}
    </div>
  );
}
