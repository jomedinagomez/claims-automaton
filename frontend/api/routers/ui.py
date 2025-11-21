"""Lightweight UI endpoints that power the HTMX front end."""

from __future__ import annotations

import html
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
import asyncio
from typing import AsyncGenerator

from ..dependencies import get_orchestrator
from ..schemas import ClaimResult, DocumentReference, EvidenceNote, ResumePayload

from claims_sk.parsers import parse_freeform_claim

_FRONTEND_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_DIR = _FRONTEND_ROOT / "templates"
_SAMPLE_PATH = _FRONTEND_ROOT / "samples" / "sample_claim.json"

templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

router = APIRouter(tags=["ui"], include_in_schema=False)


def _load_sample_claim() -> str:
    try:
        return _SAMPLE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return json.dumps({"claim": {"id": "CLM-EXAMPLE"}}, indent=2)


def _render_result_partial(request: Request, *, result=None, error: str | None = None) -> str:
    payload = {"request": request}
    if error:
        payload["error"] = error
    elif result is not None:
        payload["result"] = result if isinstance(result, dict) else result.model_dump()
    return templates.get_template("partials/result.html").render(payload)


def _build_status_summary(result: dict | None) -> dict | None:
    if not result:
        return None

    context = result.get("context") or {}
    handoff = result.get("handoff_payload") or {}
    return {
        "initialized": True,
        "status": result.get("status"),
        "termination_reason": result.get("termination_reason"),
        "rounds_executed": result.get("rounds_executed", 0),
        "missing_documents": result.get("missing_documents") or [],
        "decision": handoff.get("decision"),
        "amount": handoff.get("amount"),
        "notes": handoff.get("notes"),
        "claim_id": context.get("claim_id"),
        "policy_number": context.get("policy_number"),
        "state": context.get("state"),
    }


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    sample_claim = _load_sample_claim()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "sample_claim": sample_claim},
    )


@router.get("/ui/sample", response_class=HTMLResponse)
async def load_sample_textarea():
    sample_claim = html.escape(_load_sample_claim())
    textarea = (
        f'<textarea id="claim_json" name="claim_json" rows="16">{sample_claim}</textarea>'
    )
    return HTMLResponse(textarea)


@router.post("/ui/process-stream")
async def process_via_ui_stream(
    request: Request,
    orchestrator=Depends(get_orchestrator),
    claim_json: str | None = Form(default=None),
    claim_file: UploadFile | None = File(default=None),
):
    """Stream orchestration progress via Server-Sent Events."""
    # Handle file upload or text input
    if claim_file and claim_file.filename:
        try:
            content = await claim_file.read()
            if content:
                claim_json = content.decode('utf-8')
        except Exception as exc:
            return JSONResponse({"error": f"Could not read file: {exc}"}, status_code=400)
    
    if not claim_json or not claim_json.strip():
        return JSONResponse({"error": "Please provide a claim JSON or upload a file"}, status_code=400)
    
    # Try to parse as JSON first, if it fails treat as natural language
    try:
        normalized_claim = json.loads(claim_json)
    except json.JSONDecodeError:
        try:
            source_hint = Path(claim_file.filename) if claim_file and claim_file.filename else None
            normalized_claim = parse_freeform_claim(claim_json, source_hint)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for orchestration progress."""
        try:
            # Send initial event
            yield f"data: {json.dumps({'type': 'started', 'message': 'Processing claim...'})}\n\n"
            
            # Process with progress callback
            async def progress_callback(event_type: str, data: dict):
                event_data = {"type": event_type, **data}
                await asyncio.sleep(0)  # Allow other tasks to run
                # Store for streaming
                progress_callback.events.append(event_data)
            
            progress_callback.events = []
            
            # Patch orchestrator to emit events
            original_phase1 = orchestrator._phase1_sequential_intake
            original_phase2 = orchestrator._phase2_magentic_gathering
            original_phase3 = orchestrator._phase3_handoff_decision
            
            async def phase1_wrapper(context, history):
                await progress_callback("agent_message", {"message": "👋 Hello! I'm reviewing your claim submission. Let me validate your policy information..."})
                await progress_callback("phase", {"phase": 1, "name": "Sequential Intake", "message": "Validating policy and acknowledging claim..."})
                await original_phase1(context, history)  # Modifies context in place
                orchestrator._last_context = context  # Capture context AFTER phase completes
                
                # Check if we need information or documents after Phase 1
                missing_info = context.get("missing_information", [])
                missing_docs = context.get("missing_documents", [])
                
                if missing_info or missing_docs:
                    # Build conversational request
                    parts = []
                    if missing_info:
                        info_list = ", ".join(missing_info) if isinstance(missing_info, list) else str(missing_info)
                        parts.append(f"this information: {info_list}")
                    if missing_docs:
                        doc_list = ", ".join(missing_docs) if isinstance(missing_docs, list) else str(missing_docs)
                        parts.append(f"these documents: {doc_list}")
                    
                    request = " and ".join(parts)
                    await progress_callback("agent_message", {
                        "message": f"📋 I've reviewed your claim and I need {request}. You can provide this by typing in the chat or uploading files."
                    })
                    await progress_callback("needs_info", {
                        "claim_id": context.get("claim_id", "unknown"),
                        "missing_information": missing_info,
                        "missing_documents": missing_docs
                    })
                else:
                    await progress_callback("agent_message", {"message": "✅ Initial validation complete! Moving to detailed analysis..."})
            
            async def phase2_wrapper(context, history):
                await progress_callback("agent_message", {"message": "Policy validated! Now I'm gathering detailed information from our specialist team..."})
                await progress_callback("phase", {"phase": 2, "name": "Data Gathering", "message": "Specialist agents investigating claim details..."})
                await original_phase2(context, history)  # Modifies context in place
                orchestrator._last_context = context  # Capture context AFTER phase completes
            
            async def phase3_wrapper(context, history):
                orchestrator._last_context = context  # Capture context for missing doc detection
                await progress_callback("agent_message", {"message": "All information collected. Let me consult with our claims officer for the final decision..."})
                await progress_callback("phase", {"phase": 3, "name": "Final Decision", "message": "Claims officer making final determination..."})
                await original_phase3(context, history)  # Modifies context in place
            
            orchestrator._phase1_sequential_intake = phase1_wrapper
            orchestrator._phase2_magentic_gathering = phase2_wrapper
            orchestrator._phase3_handoff_decision = phase3_wrapper
            
            # Start background task
            task = asyncio.create_task(orchestrator.process_claim(normalized_claim))
            
            # Track if we've already notified about missing docs
            notified_missing_docs = False
            
            # Stream events as they arrive
            while not task.done():
                if progress_callback.events:
                    for event in progress_callback.events:
                        yield f"data: {json.dumps(event)}\n\n"
                        
                        # If we just emitted needs_info, stop streaming and return
                        if event.get("type") == "needs_info" and not notified_missing_docs:
                            notified_missing_docs = True
                            progress_callback.events.clear()
                            # Cancel the background task since we're pausing
                            task.cancel()
                            try:
                                await task
                            except asyncio.CancelledError:
                                pass
                            return
                    
                    progress_callback.events.clear()
                
                await asyncio.sleep(0.1)  # Reduced from 0.5 for faster response
            
            # Get final result
            result = await task
            
            # Check for missing documents in final result
            if not notified_missing_docs:
                missing_docs = result.get("missing_documents", [])
                if missing_docs:
                    claim_id = result.get("claim_id", result.get("context", {}).get("claim_id", "unknown"))
                    yield f"data: {json.dumps({'type': 'needs_info', 'claim_id': claim_id, 'documents': missing_docs, 'message': f'Please upload {len(missing_docs)} required document(s)'})}\n\n"
                    return  # Don't send completion if waiting for docs
            
            # Restore original methods
            orchestrator._phase1_sequential_intake = original_phase1
            orchestrator._phase2_magentic_gathering = original_phase2
            orchestrator._phase3_handoff_decision = original_phase3
            
            claim_result = ClaimResult.from_orchestration(result).model_dump()
            yield f"data: {json.dumps({'type': 'completed', 'result': claim_result})}\n\n"
            
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/ui/process", response_class=HTMLResponse)
async def process_via_ui(
    request: Request,
    orchestrator=Depends(get_orchestrator),
    claim_json: str | None = Form(default=None),
    claim_file: UploadFile | None = File(default=None),
):
    # Handle file upload or text input
    if claim_file and claim_file.filename:
        try:
            content = await claim_file.read()
            if content:
                claim_json = content.decode('utf-8')
        except Exception as exc:
            fragment = _render_result_partial(request, error=f"Could not read file: {exc}")
            return JSONResponse({"message_html": fragment, "status_summary": None}, status_code=400)
    
    if not claim_json or not claim_json.strip():
        fragment = _render_result_partial(
            request, error="Please provide a claim JSON or upload a file"
        )
        return JSONResponse({"message_html": fragment, "status_summary": None}, status_code=400)
    
    # Try to parse as JSON first, if it fails treat as natural language
    try:
        normalized_claim = json.loads(claim_json)
    except json.JSONDecodeError:
        try:
            source_hint = Path(claim_file.filename) if claim_file and claim_file.filename else None
            normalized_claim = parse_freeform_claim(claim_json, source_hint)
        except ValueError as exc:
            fragment = _render_result_partial(request, error=str(exc))
            return JSONResponse({"message_html": fragment, "status_summary": None}, status_code=400)

    try:
        result = await orchestrator.process_claim(normalized_claim)
    except Exception as exc:  # pragma: no cover - passthrough to UI
        fragment = _render_result_partial(request, error=str(exc))
        return JSONResponse({"message_html": fragment, "status_summary": None}, status_code=500)

    claim_result = ClaimResult.from_orchestration(result).model_dump()
    fragment = _render_result_partial(request, result=claim_result)
    return JSONResponse(
        {
            "message_html": fragment,
            "status_summary": _build_status_summary(claim_result),
        }
    )


@router.post("/ui/resume", response_class=HTMLResponse)
async def resume_via_ui(
    request: Request,
    claim_id: str = Form(...),
    note_type: str = Form(...),
    note_content: str = Form(""),
    document_type: str = Form(""),
    document_path: str = Form(""),
    orchestrator=Depends(get_orchestrator),
):
    trimmed_note = note_content.strip()
    trimmed_doc_path = document_path.strip()
    evidence_notes = (
        [EvidenceNote(type=note_type.strip(), content=trimmed_note)]
        if trimmed_note
        else None
    )

    documents = None
    if trimmed_doc_path:
        doc_type = document_type.strip() or note_type.strip()
        if not doc_type:
            return _render_result_partial(
                request, error="Specify a document type when providing a document path."
            )
        try:
            doc_ref = DocumentReference(
                type=doc_type,
                filename=Path(trimmed_doc_path).name or None,
                path=trimmed_doc_path,
            )
        except ValidationError as exc:
            messages = ", ".join(err.get("msg", "Invalid document reference") for err in exc.errors())
            return _render_result_partial(request, error=messages)
        documents = [doc_ref]

    if not evidence_notes and not documents:
        return _render_result_partial(
            request, error="Provide either inline details or a valid document path."
        )

    payload = ResumePayload(documents=documents, notes=evidence_notes).to_additional_documents()

    try:
        result = await orchestrator.continue_claim(claim_id=claim_id, additional_documents=payload)
    except ValueError as exc:
        return _render_result_partial(request, error=str(exc))
    except Exception as exc:  # pragma: no cover - passthrough to UI
        return _render_result_partial(request, error=str(exc))

    claim_result = ClaimResult.from_orchestration(result).model_dump()
    return _render_result_partial(request, result=claim_result)