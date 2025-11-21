"""Application-wide dependencies and lifespan hooks for the FastAPI service."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import HTTPException, Request

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SK_SRC = _REPO_ROOT / "platforms" / "semantic-kernel" / "src"
if str(_SK_SRC) not in sys.path:
    sys.path.insert(0, str(_SK_SRC))

logger = logging.getLogger(__name__)

from claims_sk.runtime import CoreRuntime, create_runtime
_ENV_PATH = _REPO_ROOT / ".env"
_CONFIG_DIR = _REPO_ROOT / "platforms" / "semantic-kernel" / "config"
_RUNTIME: CoreRuntime | None = None


@asynccontextmanager
async def runtime_lifespan(app) -> AsyncIterator[None]:
    """Initialize the Semantic Kernel runtime once per FastAPI lifespan."""

    global _RUNTIME

    try:
        _RUNTIME = await create_runtime(env_path=_ENV_PATH, config_dir=_CONFIG_DIR)
        app.state.orchestrator = _RUNTIME.get_orchestrator()
        logger.info("Semantic Kernel runtime initialized for FastAPI app")
        yield
    except Exception as exc:  # pragma: no cover - surfaced during startup
        logger.exception("Failed to initialize orchestration runtime: %s", exc)
        raise
    finally:
        app.state.orchestrator = None
        _RUNTIME = None
        logger.info("Semantic Kernel runtime shut down")


def get_orchestrator(request: Request):
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    return orchestrator
