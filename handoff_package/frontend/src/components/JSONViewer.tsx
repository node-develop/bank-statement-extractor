import { useMemo, useState } from "react";
import { Button } from "./ui/Button";
import { SectionLabel } from "./ui/SectionLabel";
import { IconCopy } from "./icons";

interface Props {
  data: unknown;
  height?: number;
  title?: string;
}

function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function syntaxHighlight(json: string): string {
  const safe = escapeHtml(json);
  return safe.replace(
    /("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (m) => {
      let cls = "n";
      if (/^"/.test(m)) cls = /:$/.test(m) ? "k" : "s";
      else if (/true|false|null/.test(m)) cls = "b";
      return `<span class="${cls}">${m}</span>`;
    }
  );
}

export function JSONViewer({ data, height = 480, title = "Raw extract response" }: Props) {
  const formatted = useMemo(() => JSON.stringify(data, null, 2), [data]);
  const html = useMemo(() => syntaxHighlight(formatted), [formatted]);
  const [copied, setCopied] = useState(false);

  function copy() {
    navigator.clipboard?.writeText(formatted);
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
        <SectionLabel style={{ margin: 0 }}>
          {title} <span className="mono" style={{ color: "var(--ink-4)" }}>· ExtractResult</span>
        </SectionLabel>
        <div style={{ flex: 1 }} />
        <Button variant="secondary" size="sm" onClick={copy} leftIcon={<IconCopy size={12} />}>
          {copied ? "Copied" : "Copy JSON"}
        </Button>
      </div>
      <pre
        className="json-wrap"
        style={{ maxHeight: height, margin: 0 }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
