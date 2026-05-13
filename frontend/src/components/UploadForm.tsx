import { type ChangeEvent, type FormEvent, useState } from "react";
import { ApiError, extractStatement } from "../api";
import type { ExtractResult } from "../types";

interface Props {
  onResult: (result: ExtractResult) => void;
}

function friendlyError(err: ApiError): string {
  switch (err.status) {
    case 413:
      return "File too large. PDF must be ≤ 25 MB and OCR text ≤ 5 MB.";
    case 415:
      return "Unsupported file type. Only PDF files are accepted.";
    case 422:
      return `PDF could not be read: ${err.message}`;
    default:
      return err.message || `Unexpected error (HTTP ${err.status}).`;
  }
}

export function UploadForm({ onResult }: Props) {
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [ocrFile, setOcrFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handlePdfChange(e: ChangeEvent<HTMLInputElement>) {
    setError(null);
    setPdfFile(e.target.files?.[0] ?? null);
  }

  function handleOcrChange(e: ChangeEvent<HTMLInputElement>) {
    setOcrFile(e.target.files?.[0] ?? null);
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!pdfFile) return;

    setLoading(true);
    setError(null);

    try {
      const result = await extractStatement(pdfFile, ocrFile ?? undefined);
      onResult(result);
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(friendlyError(caught));
      } else {
        setError("Network error — is the API running?");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ marginBottom: 24 }}>
      <div style={{ marginBottom: 12 }}>
        <label htmlFor="pdf-input" style={{ display: "block", fontWeight: 600, marginBottom: 4 }}>
          Bank statement PDF <span style={{ color: "#dc3545" }}>*</span>
        </label>
        <input
          id="pdf-input"
          type="file"
          accept="application/pdf"
          onChange={handlePdfChange}
          disabled={loading}
          required
        />
      </div>

      <div style={{ marginBottom: 16 }}>
        <label htmlFor="ocr-input" style={{ display: "block", fontWeight: 600, marginBottom: 4 }}>
          OCR text companion <span style={{ fontWeight: 400, color: "#6c757d" }}>(optional)</span>
        </label>
        <input
          id="ocr-input"
          type="file"
          accept=".txt,text/plain"
          onChange={handleOcrChange}
          disabled={loading}
        />
      </div>

      <button
        type="submit"
        disabled={loading || !pdfFile}
        style={{
          padding: "8px 20px",
          background: loading || !pdfFile ? "#6c757d" : "#0d6efd",
          color: "#fff",
          border: "none",
          borderRadius: 4,
          cursor: loading || !pdfFile ? "not-allowed" : "pointer",
          fontWeight: 600,
          fontSize: "0.9375rem",
        }}
      >
        {loading ? "Extracting…" : "Extract"}
      </button>

      {error !== null && (
        <div
          role="alert"
          style={{
            marginTop: 14,
            background: "#f8d7da",
            border: "2px solid #dc3545",
            borderRadius: 4,
            padding: "10px 14px",
            color: "#721c24",
          }}
        >
          {error}
        </div>
      )}
    </form>
  );
}
