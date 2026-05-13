import { useCallback, useEffect, useRef, useState } from "react";
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

const SESSION_KEY = "bsa-session";

interface SavedSession {
  phase: Phase;
  result: ExtractResult | null;
  filename: string | null;
  costUsd: string;
}

function readSession(): SavedSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as SavedSession;
  } catch {
    return null;
  }
}

function writeSession(s: SavedSession): void {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(s));
  } catch {
    // sessionStorage unavailable (e.g. private-browsing quota) — silently ignore
  }
}

function clearSession(): void {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // ignore
  }
}

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
  const saved = readSession();
  // If we were mid-processing when the page was closed, drop back to upload
  // (we cannot resume an in-flight SSE stream).
  const initialPhase: Phase = saved?.phase === "results" ? "results" : "upload";

  const [phase, setPhase] = useState<Phase>(initialPhase);
  const [progress, setProgress] = useState<ExtractionProgress>(() => {
    const p = emptyProgress();
    // Restore the final cost so the header cost strip is correct after reload.
    if (saved?.phase === "results" && saved.costUsd) {
      p.cumulative_cost_usd = saved.costUsd;
    }
    return p;
  });
  const [result, setResult] = useState<ExtractResult | null>(
    saved?.phase === "results" ? (saved.result ?? null) : null,
  );
  const [filename, setFilename] = useState<string | null>(
    saved?.phase === "results" ? (saved.filename ?? null) : null,
  );
  const [reviewing, setReviewing] = useState<PeriodResult | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  // Persist phase / result / filename / cost on every relevant state change.
  // "processing" is intentionally saved so that if the user closes and
  // reopens mid-flight, we at least know a run was in progress and can
  // show them the upload form (the initialPhase logic above handles the
  // fallback).
  useEffect(() => {
    writeSession({
      phase,
      result,
      filename,
      costUsd: progress.cumulative_cost_usd,
    });
  }, [phase, result, filename, progress.cumulative_cost_usd]);

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
          clearSession();
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
              // The streaming endpoint doesn't surface per-chunk account /
              // period info during fan-out; we only know `chunk_id`. Show a
              // neutral "Detecting…" placeholder so the chip doesn't read as
              // an error — the real month/last4 land in the results view.
              month: "Detecting…",
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
