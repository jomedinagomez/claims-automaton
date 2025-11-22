"""Customer Service Agent - Conversational interface for claim submissions."""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, HTTPException, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import ChatHistory

from ..dependencies import get_orchestrator

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SK_SRC = _REPO_ROOT / "platforms" / "semantic-kernel" / "src"
if str(_SK_SRC) not in sys.path:
    sys.path.insert(0, str(_SK_SRC))

from claims_sk.parsers import parse_freeform_claim

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DOCUMENT_ROOT = WORKSPACE_ROOT / "shared" / "submission" / "documents"
DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)

TEXT_PARSE_TYPES = {"claim_request", "claim_submission", "claim_email", "claim"}
TEXT_SUFFIXES = {".md", ".txt", ".markdown"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".heic", ".gif"}
DOC_KEYWORDS = {
    "claim_request": ("claim", "submission", "request"),
    "police_report": ("police", "report"),
    "repair_estimate": ("repair", "estimate", "body"),
    "medical_records": ("medical", "clinic", "doctor", "receipt"),
    "witness_statement": ("witness", "statement"),
    "incident_photos": ("photo", "image", "damage", "picture"),
    "rental_receipt": ("rental", "receipt"),
}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/customer-service", tags=["customer-service"])


class ChatMessage(BaseModel):
    """User message to customer service agent."""
    message: str
    claim_draft: Dict[str, Any] = {}


def _sanitize_claim_id(raw_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9-]", "", raw_id or "").upper()
    if not cleaned.startswith("CLM-"):
        cleaned = f"CLM-{cleaned or 'TEMP'}"
    return cleaned[:32]


def _normalize_doc_type(label: str | None) -> Optional[str]:
    if not label:
        return None
    normalized = re.sub(r"[^a-z0-9_ -]", "", label.lower()).strip()
    normalized = normalized.replace(" ", "_")
    return normalized or None


def _safe_filename(filename: str) -> str:
    candidate = Path(filename or "document.txt").name
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", Path(candidate).stem) or "document"
    suffix = Path(candidate).suffix
    if suffix:
        suffix = re.sub(r"[^A-Za-z0-9.]", "", suffix)
        if not suffix.startswith("."):
            suffix = f".{suffix}"
    else:
        suffix = ".txt"
    return f"{stem}{suffix}"


def _dedupe_filename(directory: Path, filename: str) -> str:
    candidate = filename
    counter = 1
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    while (directory / candidate).exists():
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _extract_claim_summary(
    *,
    normalized_type: Optional[str],
    filename: str,
    contents: bytes,
) -> Dict[str, Any] | None:
    """Attempt to parse freeform submissions for structured claim data."""

    suffix = Path(filename).suffix.lower()
    should_parse = (normalized_type in TEXT_PARSE_TYPES) or (suffix in TEXT_SUFFIXES)

    if not should_parse:
        return None

    try:
        text = contents.decode("utf-8", errors="ignore")
    except Exception:
        return None

    if not text.strip():
        return None

    try:
        parsed = parse_freeform_claim(text)
    except Exception as exc:  # pragma: no cover - heuristic best-effort
        logger.debug("Unable to parse uploaded document %s: %s", filename, exc)
        return None

    summary: Dict[str, Any] = {
        "policy_number": parsed.get("policy_number"),
        "claimant_name": parsed.get("customer", {}).get("name"),
        "contact_email": parsed.get("customer", {}).get("email"),
        "contact_phone": parsed.get("customer", {}).get("phone"),
        "incident_date": parsed.get("incident", {}).get("date"),
        "incident_location": parsed.get("incident", {}).get("location"),
        "incident_description": parsed.get("incident", {}).get("description"),
        "documents": parsed.get("documents", []),
        "original_content": parsed.get("original_content"),
    }

    return {key: value for key, value in summary.items() if value}


def _infer_document_type(
    *,
    filename: str,
    provided_type: Optional[str],
    extracted_claim: Optional[Dict[str, Any]],
) -> str:
    if extracted_claim:
        return "claim_request"
    if provided_type:
        return provided_type

    stem = Path(filename).stem.lower()
    suffix = Path(filename).suffix.lower()

    for doc_type, keywords in DOC_KEYWORDS.items():
        if any(keyword in stem for keyword in keywords):
            return doc_type

    if suffix in IMAGE_SUFFIXES:
        return "incident_photos"

    return "supporting_document"


class CustomerServiceAgent:
    """
    Overarching conversational agent that:
    1. Talks to customers about their claims
    2. Validates claim data completeness
    3. Identifies missing information
    4. Kicks off orchestration only when data is ready
    """
    
    def __init__(self, kernel: Kernel):
        self.kernel = kernel
        self.agent = self._create_agent()
        self.chat_history = ChatHistory()
        
    def _create_agent(self) -> ChatCompletionAgent:
        """Create the customer service agent."""
        
        instructions = """You are a friendly and professional insurance claims customer service representative.

Your responsibilities:
1. **Greet customers warmly** and understand what they need
2. **Ask clarifying questions** to gather complete claim information
3. **Validate claim data** - ensure all required fields are present
4. **List missing information** clearly when data is incomplete
5. **Confirm when ready** - only say "SUBMIT_CLAIM" when you have all required data

Required information for claim submission:
- policy_number: The customer's insurance policy number
- incident_date: When the incident occurred
- incident_type: Type of incident (auto, medical, property, etc.)
- incident_location: Where it happened
- incident_description: Detailed description of what happened
- total_claim_amount: Estimated or actual claim amount
- documents: At least one supporting document

Guidelines:
- Be conversational and empathetic
- Ask ONE question at a time, don't overwhelm
- If customer provides partial info, acknowledge it and ask for what's missing
- When all required fields are present, respond with: "I have all the information needed. Say 'submit' to process your claim."
- If customer says "submit" and data is complete, respond ONLY with: "SUBMIT_CLAIM"
- Never make up information - only use what the customer provides
- If customer is unsure about something, help guide them

Example conversation:
Customer: "I want to file a claim"
You: "I'd be happy to help you file a claim! Can you start by telling me your policy number?"
Customer: "POL-12345"
You: "Thank you! What type of incident are you filing for - auto, medical, property, or another type?"
...continue until all fields are collected..."""

        # Reuse the orchestrator's default chat-completion service; no explicit ID needed.
        return ChatCompletionAgent(
            kernel=self.kernel,
            name="Customer_Service_Agent",
            instructions=instructions,
        )
    
    def extract_missing_fields(self, claim_draft: Dict[str, Any]) -> list[str]:
        """Identify which required fields are missing from claim draft."""
        required = {
            "policy_number",
            "incident_date", 
            "incident_type",
            "incident_location",
            "incident_description",
            "total_claim_amount",
        }
        
        missing = []
        for field in required:
            if field not in claim_draft or not claim_draft[field]:
                missing.append(field)
        
        # Check documents
        if not claim_draft.get("documents") or len(claim_draft.get("documents", [])) == 0:
            missing.append("documents")
        
        return missing
    
    async def chat(self, user_message: str, claim_draft: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """
        Process user message and stream agent responses.
        
        Args:
            user_message: What the customer said
            claim_draft: Current state of claim data being collected
            
        Yields:
            Agent response chunks as they're generated
        """
        # Build context message with current claim state
        missing = self.extract_missing_fields(claim_draft)
        
        context_msg = f"Customer says: {user_message}\n\n"
        context_msg += "Current claim information collected:\n"
        context_msg += json.dumps(claim_draft, indent=2) + "\n\n"
        
        if missing:
            context_msg += f"Still missing: {', '.join(missing)}"
        else:
            context_msg += "All required information collected! Customer can now submit."
        
        self.chat_history.add_user_message(context_msg)
        
        # Stream agent response
        full_response = ""
        async for chunk in self.agent.invoke_stream(messages=self.chat_history.messages):
            if hasattr(chunk, 'content') and chunk.content:
                full_response += str(chunk.content)
                yield str(chunk.content)
        
        # Add assistant response to history
        self.chat_history.add_assistant_message(full_response)


# Global agent instance (in production, this should be per-session)
_agent_instance = None
_kernel_cache = None


def get_customer_service_agent(request) -> CustomerServiceAgent:
    """Get or create the customer service agent."""
    global _agent_instance, _kernel_cache
    
    # Get orchestrator which has the kernel
    orchestrator = get_orchestrator(request)
    
    # Only recreate if kernel changed or agent doesn't exist
    if _agent_instance is None or _kernel_cache != orchestrator.kernel:
        _kernel_cache = orchestrator.kernel
        _agent_instance = CustomerServiceAgent(orchestrator.kernel)
    
    return _agent_instance


@router.post("/documents/upload")
async def upload_supporting_document(
    claim_id: str = Form(...),
    document_type: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """Accept a supporting document upload and persist it for later orchestration."""

    sanitized_id = _sanitize_claim_id(claim_id)
    normalized_type = _normalize_doc_type(document_type)

    if not file.filename:
        raise HTTPException(status_code=400, detail="Upload must include a filename")

    upload_dir = DOCUMENT_ROOT / sanitized_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_filename(file.filename)
    final_name = _dedupe_filename(upload_dir, safe_name)
    destination = upload_dir / final_name

    claim_summary: Dict[str, Any] | None = None

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        destination.write_bytes(contents)
        claim_summary = _extract_claim_summary(
            normalized_type=normalized_type,
            filename=final_name,
            contents=contents,
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - file system errors surface to client
        logger.error("Failed to store uploaded document: %%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not store uploaded document") from exc

    final_type = _infer_document_type(
        filename=final_name,
        provided_type=normalized_type,
        extracted_claim=claim_summary,
    )

    relative_path = str(Path(sanitized_id) / final_name).replace("\\", "/")

    logger.info(
        "Stored uploaded document: claim_id=%s type=%s filename=%s",
        sanitized_id,
        final_type,
        final_name,
    )

    return {
        "claim_id": sanitized_id,
        "type": final_type,
        "filename": final_name,
        "relative_path": relative_path,
        "absolute_path": str(destination.resolve()),
        "size": len(contents),
        "extracted_claim": claim_summary,
    }


@router.post("/chat")
async def chat_with_agent(request: Request, chat_request: ChatMessage):
    """
    Chat with customer service agent.
    
    Streams agent responses as they're generated.
    Agent will guide customer through claim data collection.
    """
    try:
        agent = get_customer_service_agent(request)
        
        async def event_generator() -> AsyncGenerator[str, None]:
            try:
                async for chunk in agent.chat(chat_request.message, chat_request.claim_draft):
                    # Send as SSE format
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
                
                # Check if agent said to submit
                last_message = agent.chat_history.messages[-1].content if agent.chat_history.messages else ""
                
                if "SUBMIT_CLAIM" in last_message:
                    # Signal that claim is ready for orchestration
                    yield f"data: {json.dumps({'type': 'ready', 'action': 'submit'})}\n\n"
                
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                
            except Exception as e:
                logger.error("Error in chat stream: %s", e, exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    
    except Exception as e:
        logger.error("Failed to start chat: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def reset_conversation():
    """Reset the customer service conversation (start fresh)."""
    global _agent_instance
    _agent_instance = None
    return {"status": "reset", "message": "Conversation reset successfully"}
