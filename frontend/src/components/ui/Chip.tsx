import type { CSSProperties } from "react";

export type ChipKind = "success" | "warning" | "danger" | "info" | "neutral";

interface Props {
  kind: ChipKind;
  label: string;
  spinning?: boolean;
  style?: CSSProperties;
}

export function Chip({ kind, label, spinning, style }: Props) {
  return (
    <span className={`chip chip-${kind}`} style={style}>
      {spinning ? <span className="spinner-dot" /> : <span className="dot" />}
      {label}
    </span>
  );
}
