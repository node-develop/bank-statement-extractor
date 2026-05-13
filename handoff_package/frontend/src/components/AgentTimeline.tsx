import type { AgentStepProgress } from "../types-progress";
import type { AgentStepSpec } from "../lib/agentSteps";

interface Props {
  steps: AgentStepSpec[];
  /** Keyed by step_id. Missing keys render as idle. */
  progress: Record<string, AgentStepProgress>;
}

export function AgentTimeline({ steps, progress }: Props) {
  return (
    <div className="card-surface" style={{ padding: "8px 16px" }}>
      <div className="timeline">
        {steps.map((s) => {
          const p = progress[s.id] ?? { step_id: s.id, state: "idle" as const, progress: 0, elapsed_ms: 0 };
          const widthPct = p.state === "done" ? 100 : Math.max(0, Math.min(1, p.progress)) * 100;
          const t = p.elapsed_ms ? `${(p.elapsed_ms / 1000).toFixed(1)}s` : "—";
          return (
            <div key={s.id} className="lane">
              <div className={"lane-name" + (p.state === "idle" ? " idle" : "")}>
                <span className="agent-dot" style={{ background: s.color }} />
                {s.name}
                {s.runs_per_period && p.fanout ? (
                  <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)", marginLeft: 4 }}>
                    ×{p.fanout}
                  </span>
                ) : null}
              </div>
              <div className="lane-bar">
                <div
                  className={"lane-fill" + (p.state === "running" ? " running" : "")}
                  style={{ width: `${widthPct}%`, background: s.color }}
                />
              </div>
              <div className="lane-time">{t}</div>
              <div className={"lane-status " + (p.state === "done" ? "done" : p.state === "running" ? "running" : "")}>
                {p.state === "done" ? "done" : p.state === "running" ? "running" : "—"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
