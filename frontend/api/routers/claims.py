"""Claims-facing API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_orchestrator
from ..schemas import ClaimResult, ClaimSubmissionPayload, ResumePayload

router = APIRouter(prefix="/claims", tags=["claims"])


@router.post("/process", response_model=ClaimResult)
async def process_claim(
    payload: ClaimSubmissionPayload,
    orchestrator=Depends(get_orchestrator),
):
    """Kick off a new orchestration run for a normalized claim payload."""

    try:
        result = await orchestrator.process_claim(payload.claim)
    except Exception as exc:  # pragma: no cover - surfaced to API client
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ClaimResult.from_orchestration(result)


@router.post("/{claim_id}/resume", response_model=ClaimResult)
async def resume_claim(
    claim_id: str,
    payload: ResumePayload,
    orchestrator=Depends(get_orchestrator),
):
    """Resume a paused claim by submitting additional evidence."""

    additional_documents = payload.to_additional_documents()

    try:
        result = await orchestrator.continue_claim(
            claim_id=claim_id,
            additional_documents=additional_documents,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - surfaced to API client
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ClaimResult.from_orchestration(result)
