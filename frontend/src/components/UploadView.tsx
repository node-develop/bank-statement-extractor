import { type ChangeEvent, type DragEvent, type FormEvent, useState } from "react";
import { IconPlay, IconUpload } from "./icons";
import { Button } from "./ui/Button";
import { Divider, SectionLabel } from "./ui/SectionLabel";

interface Props {
  /** Called when the user clicks "Extract". */
  onSubmit: (pdf: File, ocr: File | null) => void | Promise<void>;
  /** Disable interaction while the parent is mid-request. */
  busy?: boolean;
}

export function UploadView({ onSubmit, busy }: Props) {
  const [dragging, setDragging] = useState(false);
  const [pdf, setPdf] = useState<File | null>(null);
  const [ocr, setOcr] = useState<File | null>(null);

  function pickPdf(e: ChangeEvent<HTMLInputElement>) {
    setPdf(e.target.files?.[0] ?? null);
  }
  function pickOcr(e: ChangeEvent<HTMLInputElement>) {
    setOcr(e.target.files?.[0] ?? null);
  }

  function handleDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files);
    const droppedPdf = files.find((f) => f.type === "application/pdf");
    const droppedOcr = files.find((f) => f.type === "text/plain" || f.name.endsWith(".txt"));
    if (droppedPdf) setPdf(droppedPdf);
    if (droppedOcr) setOcr(droppedOcr);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (pdf) onSubmit(pdf, ocr);
  }

  return (
    <form className="container-narrow" onSubmit={handleSubmit} style={{ paddingTop: 32 }}>
      <h1 className="t-h1" style={{ marginBottom: 8 }}>
        Extract a bank statement
      </h1>
      <p className="t-lead" style={{ marginBottom: 32 }}>
        Drop a PDF and we'll fan out a team of agents — layout classifier, account, summary,
        transactions — then verify, reconcile, and return structured JSON.
      </p>

      <label
        htmlFor="pdf-input"
        className={`upload-zone${dragging ? " dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <input
          id="pdf-input"
          type="file"
          accept="application/pdf"
          onChange={pickPdf}
          disabled={busy}
          required
          style={{ position: "absolute", width: 1, height: 1, opacity: 0, pointerEvents: "none" }}
        />
        <div className="upload-icon-wrap">
          <IconUpload size={22} />
        </div>
        <div
          style={{
            fontWeight: 600,
            fontSize: "var(--text-lg)",
            color: "var(--ink-1)",
            marginBottom: 6,
          }}
        >
          {pdf ? pdf.name : "Drop a bank-statement PDF here"}
        </div>
        <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)", marginBottom: 4 }}>
          or click to browse from disk. Up to 25 MB.
        </div>
        <div className="mono" style={{ fontSize: 11, color: "var(--ink-4)", marginTop: 10 }}>
          Optional .txt OCR companion{ocr ? ` — selected: ${ocr.name}` : ""}
          <label
            htmlFor="ocr-input"
            style={{
              marginLeft: 6,
              color: "var(--accent)",
              borderBottom: "1px solid var(--accent-tint-2)",
              cursor: "pointer",
            }}
          >
            attach
          </label>
          <input
            id="ocr-input"
            type="file"
            accept=".txt,text/plain"
            onChange={pickOcr}
            disabled={busy}
            style={{ position: "absolute", width: 1, height: 1, opacity: 0, pointerEvents: "none" }}
          />
        </div>
      </label>

      <div
        style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}
      >
        <Button
          type="submit"
          variant="primary"
          size="lg"
          disabled={!pdf || busy}
          rightIcon={<IconPlay size={13} />}
        >
          {busy ? "Extracting…" : "Extract"}
        </Button>
        <div style={{ flex: 1 }} />
        <div className="mono" style={{ fontSize: 11, color: "var(--ink-4)" }}>
          POST /extract · multipart · 80 MB cap
        </div>
      </div>

      <Divider />

      <SectionLabel>What you'll see</SectionLabel>
      <ol
        style={{
          paddingLeft: 20,
          margin: 0,
          color: "var(--ink-2)",
          fontSize: "var(--text-sm)",
          lineHeight: 1.7,
        }}
      >
        <li>Periods detected in the document (one per Statement Period header).</li>
        <li>Per-period agent timeline: classify · account · summary · transactions.</li>
        <li>Verifier checks each chunk for chain breaks, duplicates, and summary deltas.</li>
        <li>Reconciliation status + a structured JSON result you can copy.</li>
      </ol>
    </form>
  );
}
