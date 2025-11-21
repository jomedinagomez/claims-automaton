"""Pydantic schemas shared across the FastAPI routers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


class DocumentReference(BaseModel):
    """Reference to a document that already resides on the server."""

    type: str = Field(..., description="Semantic label such as 'Police Report'.")
    filename: Optional[str] = Field(None, description="Original filename (optional).")
    path: Optional[str] = Field(
        None,
        description="Path accessible to the orchestrator runtime (e.g., shared storage).",
    )

    def to_runtime_payload(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)

    @model_validator(mode="after")
    def validate_path(self) -> "DocumentReference":
        if not self.path:
            return self

        candidate = Path(self.path)
        resolved = (WORKSPACE_ROOT / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()

        try:
            resolved.relative_to(WORKSPACE_ROOT)
        except ValueError as exc:
            raise ValueError("Document path must stay within the workspace directory.") from exc

        if not resolved.exists():
            raise ValueError(f"Document path does not exist: {resolved}")

        self.path = str(resolved)
        return self


class EvidenceNote(BaseModel):
    """Inline text supplied by a claimant or adjuster to satisfy missing info."""

    type: str
    content: str

    def to_runtime_payload(self) -> Dict[str, str]:
        return self.model_dump()


class ClaimSubmissionPayload(BaseModel):
    """Normalized claim data ready to hand to the orchestrator."""

    claim: Dict[str, Any] = Field(
        ...,
        description="Structured claim payload (same shape consumed by the CLI).",
    )


class ResumePayload(BaseModel):
    """Additional evidence uploaded after a pause."""

    documents: Optional[List[DocumentReference]] = None
    notes: Optional[List[EvidenceNote]] = None

    def to_additional_documents(self) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        payload: Dict[str, List[Dict[str, Any]]] = {}
        if self.documents:
            payload["documents"] = [doc.to_runtime_payload() for doc in self.documents]
        if self.notes:
            payload["notes"] = [note.to_runtime_payload() for note in self.notes]
        return payload or None


class ClaimResult(BaseModel):
    """API-friendly view of the orchestrator result."""

    status: str
    termination_reason: Optional[str] = None
    missing_documents: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    rounds_executed: Optional[int] = None
    handoff_payload: Optional[Dict[str, Any]] = None

    @classmethod
    def from_orchestration(cls, result: Dict[str, Any]) -> "ClaimResult":
        return cls(
            status=result.get("status", "unknown"),
            termination_reason=result.get("termination_reason"),
            missing_documents=result.get("missing_documents", [])
            or result.get("context", {}).get("missing_documents", []),
            context=result.get("context", {}),
            rounds_executed=result.get("rounds_executed"),
            handoff_payload=result.get("handoff_payload"),
        )
