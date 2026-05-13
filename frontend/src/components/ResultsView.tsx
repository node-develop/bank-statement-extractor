import type { ExtractResult, PeriodResult } from "../types";
import { JSONViewer } from "./JSONViewer";
import { PeriodCard } from "./PeriodCard";
import { IconAlert, IconExternal, IconPencil } from "./icons";
import { Button } from "./ui/Button";
import { Chip } from "./ui/Chip";
import { Divider, SectionLabel } from "./ui/SectionLabel";

interface Props {
  result: ExtractResult;
  /** Optional source filename + page count for the meta line. */
  filename?: string;
  pageCount?: number;
  wallClockText?: string;
  costUsd?: number;
  onReview: (period: PeriodResult) => void;
}

export function ResultsView({
  result,
  filename,
  pageCount,
  wallClockText,
  costUsd,
  onReview,
}: Props) {
  const totalPeriods = result.periods.length;
  const reconciledCount = result.periods.filter((p) => p.reconciliation.reconciled).length;
  const allReconciled = reconciledCount === totalPeriods;
  const needsReview =
    result.pending_review != null ||
    result.periods.some((p) => (p.verifier?.suspects?.length ?? 0) > 0);
  const reviewPeriod = result.periods.find((p) => (p.verifier?.suspects?.length ?? 0) > 0);

  return (
    <div className="container" style={{ paddingTop: 8 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 14,
          marginBottom: 8,
          flexWrap: "wrap",
        }}
      >
        <h1 className="t-h2" style={{ margin: 0 }}>
          Extraction complete
        </h1>
        {allReconciled ? (
          <Chip kind="success" label="All periods reconciled" />
        ) : (
          <Chip
            kind="danger"
            label={`${totalPeriods - reconciledCount} of ${totalPeriods} not reconciled`}
          />
        )}
        <div style={{ flex: 1 }} />
        {result.langsmith_run_url && (
          <a
            href={result.langsmith_run_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ textDecoration: "none" }}
          >
            <Button variant="ghost" size="sm" leftIcon={<IconExternal size={12} />}>
              LangSmith trace
            </Button>
          </a>
        )}
      </div>

      <div
        className="mono"
        style={{
          fontSize: 11,
          color: "var(--ink-3)",
          marginBottom: 20,
          display: "flex",
          gap: 14,
          flexWrap: "wrap",
        }}
      >
        {filename && <span>{filename}</span>}
        {filename && <span>·</span>}
        {pageCount && <span>{pageCount} pages</span>}
        {pageCount && <span>·</span>}
        <span>sha256:{result.statement_sha256.slice(0, 12)}…</span>
        {(wallClockText || costUsd !== undefined) && <span>·</span>}
        {wallClockText && <span>{wallClockText}</span>}
        {costUsd !== undefined && <span>· ${costUsd.toFixed(4)}</span>}
      </div>

      <div className="stat-strip" style={{ marginBottom: 24 }}>
        <div>
          <div className="stat-label">Periods</div>
          <div className="big">
            {reconciledCount}
            <span style={{ color: "var(--ink-3)", fontWeight: 400 }}>/{totalPeriods}</span>
          </div>
          <div className="t-caption" style={{ marginTop: 2 }}>
            reconciled
          </div>
        </div>
        <div>
          <div className="stat-label">Transactions</div>
          <div className="big tnum">
            {result.periods
              .reduce((acc, p) => acc + p.summary.deposits_count + p.summary.withdrawals_count, 0)
              .toLocaleString()}
          </div>
          <div className="t-caption" style={{ marginTop: 2 }}>
            {result.periods.reduce((a, p) => a + p.summary.deposits_count, 0)} credits
            {" · "}
            {result.periods.reduce((a, p) => a + p.summary.withdrawals_count, 0)} debits
          </div>
        </div>
        <div>
          <div className="stat-label">Status</div>
          <div className="big" style={{ fontSize: "var(--text-base)", paddingTop: 6 }}>
            {allReconciled ? "All reconciled" : "Needs review"}
          </div>
        </div>
      </div>

      {needsReview && reviewPeriod && (
        <div
          style={{
            background: "var(--danger-bg)",
            border: "1px solid var(--danger-border)",
            borderRadius: "var(--radius-3)",
            padding: "12px 16px",
            marginBottom: 20,
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <IconAlert size={18} style={{ color: "var(--danger-fg)" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, color: "var(--danger-fg)" }}>Review required.</div>
            <div className="t-small" style={{ color: "var(--ink-2)" }}>
              The verifier flagged suspects in <span className="mono">{reviewPeriod.chunk_id}</span>
              . Open the review to inspect, edit, or force-finalize.
            </div>
          </div>
          <Button
            variant="danger-ghost"
            onClick={() => onReview(reviewPeriod)}
            leftIcon={<IconPencil size={12} />}
          >
            Open review
          </Button>
        </div>
      )}

      {result.errors.length > 0 && (
        <div
          style={{
            background: "var(--warning-bg)",
            border: "1px solid var(--warning-border)",
            borderRadius: "var(--radius-3)",
            padding: "10px 14px",
            marginBottom: 20,
            color: "var(--warning-fg)",
          }}
        >
          <strong style={{ fontWeight: 600 }}>Pipeline warnings ({result.errors.length}):</strong>
          <ul style={{ margin: "6px 0 0 0", paddingLeft: 20, fontSize: "var(--text-sm)" }}>
            {result.errors.map((e, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: errors are positional pipeline notes with no stable id
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      <SectionLabel>
        Periods{" "}
        <span className="mono" style={{ color: "var(--ink-4)" }}>
          · click to expand
        </span>
      </SectionLabel>
      <div style={{ marginBottom: 24 }}>
        {result.periods.map((p, i) => (
          <PeriodCard
            key={p.chunk_id}
            period={p}
            initialOpen={i === 0}
            transactions={p.transactions}
            onReview={onReview}
          />
        ))}
      </div>

      <Divider />

      <JSONViewer data={result} />
    </div>
  );
}
