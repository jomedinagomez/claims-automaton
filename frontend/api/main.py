"""FastAPI entry point for the claims orchestration service."""

from __future__ import annotations

from fastapi import FastAPI

from .dependencies import runtime_lifespan
from .routers import claims, ui, customer_service

app = FastAPI(
    title="Claims Orchestration API",
    version="0.1.0",
    lifespan=runtime_lifespan,
)

app.include_router(ui.router)
app.include_router(claims.router)
app.include_router(customer_service.router)


@app.get("/healthz", tags=["system"])
async def health_check() -> dict[str, str]:
    """Simple health endpoint for readiness probes."""

    return {"status": "ok"}
