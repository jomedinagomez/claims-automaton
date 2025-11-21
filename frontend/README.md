# Shared Frontend

Single UI surface for claims agents. The frontend will:
- present the AI-generated assessment briefs and supporting evidence;
- capture the agent's approve/deny choice plus rationale;
- call whichever backend (`semantic-kernel`, `agent-framework`, `azure-ai-foundry`) is active for the environment.

## Implementation Notes
- Framework is still TBD (React + Vite is the leading option), but the directory exists now so routing, component, and API conventions can be documented early.
- All backend selection should flow through a small API client layer that reads environment variables (e.g., `VITE_BACKEND_TARGET=semantic-kernel`).
- The frontend should treat the shared fixtures as sample data sources for Storybook or component tests so the UI reflects realistic claim narratives/documents.
 
## Python-first API Surface

A FastAPI service now lives in `frontend/api` so Python teams can build HTMX/Alpine or template-driven experiences without reaching back into the CLI. The service wires directly into the Semantic Kernel runtime:

```pwsh
cd frontend
uv pip install fastapi "uvicorn[standard]"
uv run uvicorn api.main:app --reload
```

Endpoints:
- `POST /claims/process` — submit normalized claim payloads (same shape as the CLI `claim_data`).
- `POST /claims/{claim_id}/resume` — attach inline notes or documents to resume paused flows.
- `GET /healthz` — simple readiness probe.
