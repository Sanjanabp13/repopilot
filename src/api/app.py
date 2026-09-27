"""FastAPI application factory for RepoPilot."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import analyze, trace, diagram, impact, chat, export

app = FastAPI(
    title="RepoPilot (TraceMind)",
    description="AI-driven developer onboarding assistant — analyze repos, trace execution paths, blast-radius impact.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze.router)
app.include_router(trace.router)
app.include_router(diagram.router)
app.include_router(impact.router)
app.include_router(chat.router)
app.include_router(export.router)


@app.get("/health")
def health():
    return {"status": "ok"}
