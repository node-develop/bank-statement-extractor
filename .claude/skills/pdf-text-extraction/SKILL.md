---
name: pdf-text-extraction
description: Decision tree and code patterns for extracting text/tables from bank-statement PDFs — pdfplumber first, pypdf fallback, OCR-as-input acceptance. Use when implementing `ingest` node or when extraction misses rows. Do NOT use for image-only PDFs (those require OCR upstream).
---

# PDF text extraction strategy

## Library matrix

| Library    | Strength                          | Use when                  |
|------------|-----------------------------------|---------------------------|
| pdfplumber | Tables with positional fidelity   | Primary — always try first|
| pypdf      | Stream text, fewer deps           | Fallback if pdfplumber fails to open |
| OCR text   | When PDF has no embedded text     | Caller supplies `.txt`    |

## Algorithm

```python
def ingest(pdf_path: str, txt_path: str | None) -> RawStatement:
    pages: list[str] = []
    tables: list[list[list[str]]] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
                tables.append(page.extract_tables() or [])
    except Exception:
        # Fallback to pypdf — no table extraction here
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pages = [p.extract_text() or "" for p in reader.pages]
        tables = [[] for _ in pages]

    ocr_text = Path(txt_path).read_text() if txt_path else None
    sha = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    return RawStatement(pages=pages, tables=tables, ocr_text=ocr_text, sha256=sha)
```

## When pdfplumber and OCR disagree

Rule 7 — surface conflicts, don't average. Prefer pdfplumber tables for
transactions (positional fidelity), and OCR for descriptions when the PDF
text contains "fake spaces" introduced by hyphenation/wrapping. Annotate
each transaction with `source: "pdf" | "ocr"` to keep it auditable.

## Anti-patterns

- Running pdfplumber AND pypdf and concatenating outputs. Pick one
  source-of-truth per field.
- Using `pytesseract` to "improve" already-OCR'd text. We do not run OCR
  ourselves; OCR text is an input.
- Trusting `page.extract_text()` whitespace. Banks use fixed-width layout
  — use `page.extract_tables()` for transactions, regex on `extract_text()`
  only for the summary block.
