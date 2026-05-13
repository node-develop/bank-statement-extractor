import { Button } from "./ui/Button";
import { IconFile, IconRefresh, IconZap } from "./icons";

interface Props {
  /** Filename to show in the meta row (null = hide) */
  subtitle?: string | null;
  /** Cumulative LLM cost (USD). Null/undefined hides the ticker. */
  cost?: number | null;
  /** Show the "New extract" reset button */
  showReset?: boolean;
  onReset?: () => void;
}

export function Header({ subtitle, cost, showReset, onReset }: Props) {
  return (
    <header className="header">
      <div className="header-inner">
        <a
          className="header-logo"
          href="#"
          onClick={(e) => { e.preventDefault(); onReset?.(); }}
          aria-label="Bank Statement Extractor — home"
        >
          <img src="/logo.svg" alt="Bank Statement Extractor" />
        </a>
        <div className="header-spacer" />
        {subtitle && (
          <div className="header-meta">
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <IconFile size={13} style={{ color: "var(--ink-3)" }} />
              {subtitle}
            </span>
          </div>
        )}
        {cost !== undefined && cost !== null && (
          <div className="cost-ticker" title="Cumulative LLM cost (cap $5.00)">
            <IconZap size={11} style={{ color: "var(--ink-3)" }} />
            ${cost.toFixed(4)}
          </div>
        )}
        {showReset && (
          <Button variant="ghost" size="sm" onClick={onReset} leftIcon={<IconRefresh size={12} />}>
            New extract
          </Button>
        )}
      </div>
    </header>
  );
}
