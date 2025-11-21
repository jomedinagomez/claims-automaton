# Session Persistence Implementation - Summary

## What Was Implemented

✅ **Complete session persistence system** for multi-step claim workflows with pause/resume capability.

## Components Added/Updated

### 1. SessionStore (`session_store.py`)
- **Restored from stub** to full implementation (250+ lines)
- Manages persistent storage in `sessions/{claim_id}/` directories
- Serializes/deserializes ChatHistory and context metadata
- Methods: `save_session()`, `load_session()`, `session_exists()`, `list_sessions()`, `archive_session()`

### 2. ClaimsOrchestrator (`orchestration.py`)
- **Added session persistence hooks**:
  - Auto-saves at phase boundaries when paused
  - Archives completed sessions
  - Detects pause conditions via `_should_pause()`
- **New method**: `continue_claim(claim_id, additional_documents)` - Resume paused claims
- **Updated**: `process_claim()` - Now accepts `existing_context` for resume
- **Updated**: `__init__()` - Now accepts `session_store` parameter

### 3. CLI Commands (`cli.py`)
- **New command**: `resume` - Resume paused claim with additional documents
  - Example: `python -m claims_sk.cli resume CLM-123 -d ./new_docs`
- **New command**: `list-sessions` - View all saved sessions
  - Displays table with claim ID, status, message count, timestamps
- **Updated**: `process` - Now auto-pauses and saves when documents missing

### 4. Build Orchestrator (`orchestration.py`)
- **Updated**: `build_orchestrator()` - Now creates SessionStore if persistence enabled
- Config options: `enable_session_persistence`, `session_dir`

## Storage Format

Each session stored in `sessions/{claim_id}/`:
```
session.json      # Metadata (timestamps, status, message_count)
context.json      # Orchestration context (state, risk_score, missing_documents)
history.jsonl     # Chat history (one message per line)
```

## Pause/Resume Logic

### When Orchestration Pauses
1. Phase 1 complete + `missing_documents` non-empty
2. Phase 2 complete + agents discover more missing items
3. Condition: `enable_human_in_loop=True` (default)

### What Gets Saved
- Complete ChatHistory (all agent messages)
- Full orchestration context
- Session metadata (timestamps, status)

### Resume Behavior
1. Load saved session from disk
2. Update context with new documents
3. Remove resolved items from `missing_documents`
4. Add system message about document receipt
5. Resume orchestration from saved state
6. Archive when complete

## Usage Examples

### CLI
```powershell
# Submit claim (auto-pauses if docs missing)
python -m claims_sk.cli process claim.md

# Resume with additional documents
python -m claims_sk.cli resume CLM-123 -d ./new_docs

# List all saved sessions
python -m claims_sk.cli list-sessions
```

### Programmatic
```python
# Submit claim
result = await orchestrator.process_claim(claim_data)

if result["status"] == "paused":
    # Resume later
    result = await orchestrator.continue_claim(
        claim_id="CLM-123",
        additional_documents={"documents": [...]},
    )
```

### Backend API Pattern
```python
# POST /claims
result = await orchestrator.process_claim(claim_data)

# POST /claims/{claim_id}/continue
result = await orchestrator.continue_claim(claim_id, documents)
```

## Documentation

- **Primary**: `docs/SESSION_PERSISTENCE.md` - Complete guide with architecture, API, examples
- **Example**: `examples/backend_api_example.py` - Backend service pattern demo
- **Updated**: `README.md` - New CLI commands and usage patterns

## Testing

Validated:
- ✅ Imports work correctly
- ✅ CLI shows new commands (`resume`, `list-sessions`)
- ✅ SessionStore methods functional
- ✅ Orchestrator integration

## Architecture Decision

**Backend ownership** (as discussed):
- Session persistence managed by orchestration service layer
- Frontend calls backend API endpoints
- Backend enforces access control, validates documents, manages state
- Audit trail maintained in backend logs

## Configuration

Default behavior:
- Session persistence: **Enabled** by default
- Storage location: `./sessions/` (configurable)
- Human-in-loop: **Enabled** by default (required for pause behavior)

Disable if needed:
```python
config = {
    "enable_session_persistence": False,  # Disable persistence
}
```

## Next Steps (Optional)

Future enhancements could include:
- TTL/expiration for old sessions
- Cloud storage backends (Azure Blob, S3)
- Encryption for sensitive context data
- Webhooks for async resume notifications
- Compression for large chat histories

## Migration Note

The previous simplified demo had a SessionStore stub that raised RuntimeError.
This has been **completely replaced** with full implementation - no migration needed for new installs.

If you have existing code importing SessionStore, it will now work correctly instead of raising an error.
