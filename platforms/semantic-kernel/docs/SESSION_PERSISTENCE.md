# Session Persistence for Claims Orchestration

This document describes the session persistence feature for multi-step claim workflows with pause/resume capability.

## Overview

Session persistence enables the orchestrator to save conversation state when claims are paused (e.g., due to missing documents) and resume processing when the customer provides additional information.

## Architecture

### Components

1. **SessionStore** (`session_store.py`)
   - Manages persistent storage of chat history and context
   - Serializes/deserializes Semantic Kernel ChatHistory objects
   - Stores sessions in `sessions/{claim_id}/` directory structure

2. **ClaimsOrchestrator** (`orchestration.py`)
   - Detects pause conditions (missing documents with human-in-loop enabled)
   - Saves session snapshots automatically at phase boundaries
   - Provides `continue_claim()` method for resuming paused claims

3. **CLI Commands** (`cli.py`)
   - `process` - Submit new claim (auto-pauses if docs missing)
   - `resume` - Resume paused claim with additional documents
   - `list-sessions` - View all saved sessions

## Storage Format

Each session is stored in `sessions/{claim_id}/` with three files:

```
sessions/
  CLM-1120105522/
    session.json      # Metadata (timestamps, status, message count)
    context.json      # Orchestration context (state, risk_score, etc.)
    history.jsonl     # Chat history (one message per line)
```

### session.json
```json
{
  "claim_id": "CLM-1120105522",
  "saved_at": "2025-11-20T15:30:45Z",
  "message_count": 12,
  "status": "paused_after_phase1",
  "missing_documents": [
    "vehicle_damage_photos",
    "insurance_exchange_form"
  ]
}
```

### context.json
```json
{
  "claim_id": "CLM-1120105522",
  "policy_number": "AUTO-789456",
  "state": "validation_complete",
  "missing_documents": ["vehicle_damage_photos", "insurance_exchange_form"],
  "risk_score": 0,
  "ack_sent": true
}
```

### history.jsonl
```jsonl
{"role": "user", "content": "New claim submission:\n\nClaim ID: CLM-1120105522...", "name": null, "metadata": {}}
{"role": "assistant", "content": "Acknowledged. Reviewing policy AUTO-789456...", "name": "intake_coordinator", "metadata": {}}
{"role": "system", "content": "System note: Missing documents: vehicle_damage_photos, insurance_exchange_form", "name": null, "metadata": {}}
```

## Usage

### Command Line Interface

#### Submit New Claim
```bash
python -m claims_sk.cli process shared/submission/claim_submission.md -o output/
```

If documents are missing, the orchestrator will:
1. Save session to `sessions/{claim_id}/`
2. Return status `"paused"`
3. List required documents

#### Resume Paused Claim
```bash
python -m claims_sk.cli resume CLM-1120105522 -d ./additional_docs -o output/
```

This will:
1. Load saved session from `sessions/CLM-1120105522/`
2. Process additional documents from `./additional_docs/`
3. Resume orchestration from saved state
4. Archive session when complete

#### List Saved Sessions
```bash
python -m claims_sk.cli list-sessions
```

Displays table of all saved sessions with status and timestamps.

### Backend API Integration

See `examples/backend_api_example.py` for complete implementation pattern.

```python
from claims_sk.runtime import create_runtime

# Initialize service
runtime = await create_runtime()
orchestrator = runtime.get_orchestrator()

# Submit new claim
result = await orchestrator.process_claim(claim_data)
if result["status"] == "paused":
    missing_docs = result["missing_documents"]
    # Return to frontend: "Please upload: {missing_docs}"

# Resume with additional documents
result = await orchestrator.continue_claim(
    claim_id="CLM-1120105522",
    additional_documents={"documents": [...]},
)
```

### Programmatic API

```python
from claims_sk.session_store import SessionStore
from semantic_kernel.contents import ChatHistory

# Create session store
store = SessionStore(base_dir="./sessions")

# Save session
store.save_session(
    claim_id="CLM-123",
    chat_history=chat_history,
    context=context,
    metadata={"status": "paused"},
)

# Load session
session_data = store.load_session("CLM-123")
chat_history = session_data["chat_history"]
context = session_data["context"]

# Check existence
if store.session_exists("CLM-123"):
    # Resume processing
    pass

# List all sessions
claim_ids = store.list_sessions()

# Archive completed session
store.archive_session("CLM-123")
```

## Configuration

Session persistence is enabled by default. To configure:

```python
orchestrator = ClaimsOrchestrator(
    kernel=kernel,
    agents=agents,
    enable_human_in_loop=True,  # Required for pause behavior
    session_store=SessionStore(base_dir="./custom_sessions"),
)
```

Or via `build_orchestrator()`:

```python
orchestrator = await build_orchestrator(
    kernel=kernel,
    agents=agents,
    config={
        "enable_human_in_loop": True,
        "enable_session_persistence": True,
        "session_dir": "./custom_sessions",
    },
)
```

## Pause/Resume Logic

### When Does Orchestration Pause?

1. **Phase 1 Complete**: If `missing_documents` list is non-empty after Phase 1 (intake/validation)
2. **Phase 2 Complete**: If agents discover additional missing items during Phase 2 (specialist gathering)
3. **Condition**: `enable_human_in_loop=True` (default)

### What Gets Saved?

- Complete ChatHistory (all agent messages)
- Orchestration context (state, risk_score, missing_documents, etc.)
- Session metadata (timestamps, status, message count)

### Resume Behavior

When `continue_claim()` is called:

1. Load saved session from disk
2. Update context with new documents
3. Remove resolved items from `missing_documents` list
4. Add system message about document receipt
5. Resume orchestration from saved phase
6. Archive session when complete (approved/denied)

## Security Considerations

### Backend Ownership

Session persistence should be managed by the **backend orchestration service**, not the frontend:

- **Access Control**: Backend enforces user authentication before loading sessions
- **Data Integrity**: Backend validates documents before updating context
- **Audit Trail**: Backend logs all resume operations with user identity
- **State Consistency**: Backend ensures chat history and context remain synchronized

### Recommended Architecture

```
Frontend (React/Vue)
    ↓ POST /claims
Backend API (FastAPI/Flask)
    ↓ orchestrator.process_claim()
Orchestration Service
    ↓ session_store.save_session()
Persistent Storage (sessions/)
```

For resume:

```
Frontend (React/Vue)
    ↓ POST /claims/{claim_id}/continue + documents
Backend API (FastAPI/Flask)
    ↓ Validate user owns claim
    ↓ orchestrator.continue_claim()
Orchestration Service
    ↓ session_store.load_session()
    ↓ Resume processing
    ↓ session_store.archive_session()
```

## Error Handling

### Session Not Found
```python
try:
    result = await orchestrator.continue_claim("CLM-MISSING")
except ValueError as e:
    # "No saved session found for claim_id: CLM-MISSING"
    return {"error": "Claim not found"}, 404
```

### Invalid Documents
```python
# Backend should validate documents before calling continue_claim()
if not all(doc["type"] in allowed_types for doc in documents):
    return {"error": "Invalid document types"}, 400
```

### Corrupted Session
```python
# SessionStore handles JSON decode errors gracefully
session_data = store.load_session(claim_id)
if not session_data:
    # Corrupt or missing files
    return {"error": "Session corrupted"}, 500
```

## Testing

See `tests/test_session_store.py` for unit tests:

```python
def test_save_and_load_session():
    store = SessionStore(base_dir="./test_sessions")
    
    # Create test session
    chat_history = ChatHistory()
    chat_history.add_message(ChatMessageContent(role=AuthorRole.USER, content="Test"))
    
    context = {"claim_id": "TEST-001", "state": "paused"}
    
    # Save
    store.save_session("TEST-001", chat_history, context)
    
    # Load
    session_data = store.load_session("TEST-001")
    assert len(session_data["chat_history"].messages) == 1
    assert session_data["context"]["state"] == "paused"
```

## Future Enhancements

- **TTL/Expiration**: Auto-delete sessions older than 30 days
- **Compression**: Compress chat history for large sessions
- **Cloud Storage**: Support Azure Blob Storage / S3 backends
- **Versioning**: Track session schema versions for migrations
- **Encryption**: Encrypt sensitive context data at rest
- **Webhooks**: Notify frontend when resume is complete (async processing)

## Related Documentation

- [Orchestration Flow](../docs/orchestration.md)
- [Backend API Pattern](./backend_api_example.py)
- [CLI Reference](../README.md#cli-commands)
