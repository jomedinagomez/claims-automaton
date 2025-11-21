# Session Persistence - Quick Reference

## Commands

```powershell
# Process new claim
python -m claims_sk.cli process claim.md -o ./output

# Resume paused claim
python -m claims_sk.cli resume CLM-123 -d ./new_docs -o ./output

# List saved sessions
python -m claims_sk.cli list-sessions

# Check version
python -m claims_sk.cli version
```

## Python API

```python
from claims_sk.runtime import create_runtime

# Initialize
runtime = await create_runtime()
orchestrator = runtime.get_orchestrator()

# Process claim
result = await orchestrator.process_claim(claim_data)

# Check if paused
if result["status"] == "paused":
    missing = result["missing_documents"]
    
# Resume claim
result = await orchestrator.continue_claim(
    claim_id="CLM-123",
    additional_documents={"documents": [...]},
)
```

## SessionStore API

```python
from claims_sk.session_store import SessionStore

store = SessionStore(base_dir="./sessions")

# Save session
store.save_session(claim_id, chat_history, context, metadata)

# Load session
session_data = store.load_session(claim_id)
chat_history = session_data["chat_history"]
context = session_data["context"]

# Check existence
if store.session_exists(claim_id):
    pass

# List all
claim_ids = store.list_sessions()

# Archive
store.archive_session(claim_id)
```

## Storage Structure

```
sessions/
  CLM-123/
    session.json    # Metadata
    context.json    # Orchestration state
    history.jsonl   # Chat messages
```

## Result Status Codes

- `"paused"` - Missing documents, waiting for customer
- `"approved"` - Claim approved, handoff ready
- `"denied"` - Claim denied, denial package ready
- `"stalled"` - Agents not making progress
- `"timeout"` - Max rounds exceeded
- `"error"` - Exception occurred

## Configuration

`.env` settings:
```bash
ORCHESTRATION_ENABLE_HITL=true    # Required for pause behavior
ORCHESTRATION_MAX_ROUNDS=15
ORCHESTRATION_STALL_THRESHOLD=3
```

Python config:
```python
config = {
    "enable_human_in_loop": True,
    "enable_session_persistence": True,
    "session_dir": "./custom_sessions",
    "max_rounds": 15,
    "stall_threshold": 3,
}
orchestrator = await build_orchestrator(kernel, agents, config)
```

## Backend API Pattern

```python
class ClaimsBackendService:
    async def submit_claim(self, claim_data):
        result = await self.orchestrator.process_claim(claim_data)
        return {
            "claim_id": claim_data["claim_id"],
            "status": result["status"],
            "missing_documents": result.get("missing_documents", []),
        }
    
    async def continue_claim(self, claim_id, documents):
        result = await self.orchestrator.continue_claim(claim_id, documents)
        return {"status": result["status"]}
```

## Common Patterns

### Check for missing documents
```python
result = await orchestrator.process_claim(claim_data)
if result["status"] == "paused":
    print(f"Missing: {result['missing_documents']}")
```

### Resume with documents
```python
documents = {
    "documents": [
        {"type": "vehicle_damage_photos", "filename": "damage.jpg"},
        {"type": "insurance_exchange_form", "filename": "exchange.pdf"},
    ]
}
result = await orchestrator.continue_claim("CLM-123", documents)
```

### List all paused claims
```python
sessions = orchestrator.session_store.list_sessions()
for claim_id in sessions:
    session_data = orchestrator.session_store.load_session(claim_id)
    if session_data["metadata"]["status"].startswith("paused"):
        print(f"Paused: {claim_id}")
```

## Documentation Links

- [Full Guide](SESSION_PERSISTENCE.md)
- [Backend Example](../examples/backend_api_example.py)
- [Implementation Summary](SESSION_IMPLEMENTATION_SUMMARY.md)
