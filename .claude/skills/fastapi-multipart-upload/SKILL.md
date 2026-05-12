---
name: fastapi-multipart-upload
description: Pattern for FastAPI POST endpoint accepting a PDF via multipart/form-data, with size limits, content-type validation, sha256 hashing, and graph invocation. Use when implementing `POST /extract`. Do NOT use for base64 JSON uploads.
---

# FastAPI multipart upload pattern

## Endpoint

```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from hashlib import sha256
from src.graph import build_graph

router = APIRouter()
graph = build_graph()
MAX_BYTES = 25 * 1024 * 1024  # 25 MB

@router.post("/extract")
async def extract(file: UploadFile = File(...)) -> ExtractResponse:
    if file.content_type not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(415, "Only application/pdf is accepted")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"Max upload size is {MAX_BYTES} bytes")
    digest = sha256(data).hexdigest()
    # Persist to a temp path; graph reads from disk
    tmp = Path(tempfile.mkdtemp()) / file.filename
    tmp.write_bytes(data)
    state = await graph.ainvoke(
        {"pdf_path": str(tmp), "txt_path": None},
        config={"run_name": f"unknown:{digest[:8]}",
                "tags": ["extract"],
                "metadata": {"statement_sha256": digest}},
    )
    return ExtractResponse(**state["finalized"])
```

## Why not stream the body

We need the full bytes for sha256 anyway, and PDFs are bounded (25 MB).
Streaming would complicate the temp-file write without saving memory at
this scale.

## CORS

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)
```

## Anti-patterns

- Trusting `file.size` — it's optional in the multipart spec.
- Forgetting to delete the temp file. Use a `BackgroundTask` or
  `tempfile.NamedTemporaryFile(delete=True)`.
- Returning the raw graph state. Always pass through a Pydantic response
  model so the wire schema is stable.
