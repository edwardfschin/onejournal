"""Loopback-safe FastAPI application for the versioned fixture boundary."""

from __future__ import annotations

from fastapi import FastAPI

from .contracts import PreviewResponse
from .fixtures import build_preview_fixture


app = FastAPI(
    title="OneJournal API",
    version="0.1.0",
    description=(
        "A versioned, read-only demonstration boundary. It exposes only "
        "deterministic non-private fixtures and has no broker or database access."
    ),
)


@app.get("/api/v1/preview", response_model=PreviewResponse, tags=["fixtures"])
def get_preview() -> PreviewResponse:
    """Return the static synthetic preview contract."""

    return build_preview_fixture()
