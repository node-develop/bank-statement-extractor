"""Top-level entrypoint shim. Real app lives in src/api/main.py.

Run with:
    uv run uvicorn src.api.main:app --reload
"""

from src.api.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000)  # noqa: S104
