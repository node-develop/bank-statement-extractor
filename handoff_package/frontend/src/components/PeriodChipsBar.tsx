import type { PeriodVisualState } from "../types-progress";

export interface PeriodChip {
  id: string;
  month: string;       // "Apr 2025"
  last4: string;       // "4664"
}

interface Props {
  periods: PeriodChip[];
  /** Keyed by chip id; missing → "pending". */
  periodStates: Record<string, PeriodVisualState>;
  onClickPeriod?: (id: string) => void;
}

export function PeriodChipsBar({ periods, periodStates, onClickPeriod }: Props) {
  return (
    <div className="period-bar">
      {periods.map((p) => {
        const st = periodStates[p.id] ?? "pending";
        return (
          <span
            key={p.id}
            className={`period-chip ${st}`}
            onClick={() => onClickPeriod?.(p.id)}
            title={`${p.id} · ${p.month} · ${p.last4}`}
          >
            {st === "running" ? (
              <span className="spinner-dot" style={{ width: 8, height: 8, borderColor: "currentColor", borderTopColor: "transparent" }} />
            ) : (
              <span className="dot" />
            )}
            {p.month}
            <span className="last4">· {p.last4}</span>
          </span>
        );
      })}
    </div>
  );
}
