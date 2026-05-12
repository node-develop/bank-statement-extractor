"""bank-statement-analizer — FastAPI entrypoint.

This module is intentionally minimal at scaffold time. The `fastapi-engineer`
subagent owns expanding it. See `.claude/agents/fastapi-engineer.md`.
"""
from __future__ import annotations

import os

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="bank-statement-analizer", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return {"status": "not_ready", "reason": "ANTHROPIC_API_KEY missing"}
        return {"status": "ready"}

    return app


app = create_app()
