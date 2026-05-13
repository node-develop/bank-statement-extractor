import { AGENT_STEPS } from "../lib/agentSteps";
import type { ExtractionProgress } from "../types-progress";
import { AgentTimeline } from "./AgentTimeline";
import { type PeriodChip, PeriodChipsBar } from "./PeriodChipsBar";
import { Button } from "./ui/Button";
import { SectionLabel } from "./ui/SectionLabel";

interface Props {
  progress: ExtractionProgress;
  /** Periods extracted from the document — chips render in this order. */
  periods?: PeriodChip[];
  onCancel?: () => void;
}

export function ProcessingView({ progress, periods = [], onCancel }: Props) {
  const stepMap = Object.fromEntries(progress.steps.map((s) => [s.step_id, s]));
  const activeStep = AGENT_STEPS.find((s) => s.id === progress.active_step) ?? AGENT_STEPS[0];

  return (
    <div className="container" style={{ paddingTop: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 18 }}>
        <h1 className="t-h2" style={{ margin: 0 }}>
          Extracting…
        </h1>
        <span className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
          {activeStep.desc}
        </span>
        <div style={{ flex: 1 }} />
        {onCancel && (
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>

      <div className="stat-strip" style={{ marginBottom: 20 }}>
        <div>
          <div className="stat-label">Periods detected</div>
          <div className="big">{periods.length || "—"}</div>
        </div>
        <div>
          <div className="stat-label">Active step</div>
          <div
            className="big"
            style={{
              fontSize: "var(--text-base)",
              fontWeight: 600,
              color: "var(--ink-1)",
              paddingTop: 6,
            }}
          >
            <span className="mono">{progress.active_step}</span>
          </div>
        </div>
        <div>
          <div className="stat-label">Cost</div>
          <div className="big tnum">${progress.cumulative_cost_usd}</div>
        </div>
        <div>
          <div className="stat-label">Cap</div>
          <div className="big tnum">$5.0000</div>
        </div>
      </div>

      {periods.length > 0 && (
        <>
          <SectionLabel>Periods</SectionLabel>
          <div style={{ marginBottom: 24 }}>
            <PeriodChipsBar periods={periods} periodStates={progress.period_states} />
          </div>
        </>
      )}

      <SectionLabel>Agent pipeline</SectionLabel>
      <AgentTimeline steps={AGENT_STEPS} progress={stepMap} />

      {!AGENT_STEPS.some((s) => s.id === progress.active_step) && progress.active_step !== "" && (
        <div
          style={{
            marginTop: 14,
            padding: "8px 12px",
            borderRadius: "var(--radius-2)",
            background: "var(--surface-2)",
            border: "1px solid var(--border-1)",
            fontSize: 12,
            color: "var(--ink-3)",
          }}
        >
          <span className="mono" style={{ color: "var(--ink-2)" }}>
            {progress.active_step}
          </span>
          {" — "}
          {progress.active_step === "critic" && "Critic loop reviewing extraction…"}
          {progress.active_step === "apply_critic_hint" && "Applying critic hint…"}
          {progress.active_step === "await_review" && "Awaiting human review…"}
          {progress.active_step === "merge_state" && "Merging fan-out results…"}
          {progress.active_step === "finalize" && "Finalising response…"}
        </div>
      )}

      {progress.thread_id && (
        <div className="mono" style={{ marginTop: 14, fontSize: 11, color: "var(--ink-4)" }}>
          thread_id: {progress.thread_id} · LangSmith trace will be attached on completion.
        </div>
      )}
    </div>
  );
}
