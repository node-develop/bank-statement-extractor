import type { CSSProperties, ReactNode } from "react";

export function SectionLabel({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <div className="section-label" style={style}>{children}</div>;
}

export function Divider({ style }: { style?: CSSProperties }) {
  return <div className="hr" style={style} />;
}
