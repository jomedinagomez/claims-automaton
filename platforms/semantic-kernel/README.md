# Semantic Kernel Claims Orchestration

Mixed pattern orchestration (Sequential → Magentic → Handoff) for insurance claims processing using **native Semantic Kernel features**.

## Architecture

This implementation uses:
- **MagenticOrchestration**: Native SK orchestration for adaptive specialist agent selection
- **ClaimsMagenticManager**: Custom termination manager extending `StandardMagenticManager`
- **Auto Function Calling**: Automatic tool invocation for specialist agents
- **Agent.InvokeAsync()**: Explicit checkpoints for human-in-loop approval

### Three-Phase Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 1: Sequential Intake (Deterministic)                      │
├─────────────────────────────────────────────────────────────────┤
│ 1. IntakeCoordinator: Send acknowledgment, validate policy     │
│ 2. DocumentValidator: Check completeness, identify missing docs│
│ → Updates: ack_sent, missing_documents, state="validation"     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Phase 2: Magentic Adaptive Gathering (Dynamic)                 │
├─────────────────────────────────────────────────────────────────┤
│ MagenticOrchestration with ClaimsMagenticManager:              │
│ • PolicySpecialist: Coverage verification                       │
│ • FraudAnalyst: Risk scoring, blacklist checks                 │
│ • MedicalSpecialist: Medical code validation (if applicable)   │
│ • HistoryAnalyst: Prior claims lookup                          │
│ • VendorSpecialist: Vendor verification (if applicable)        │
│                                                                 │
│ Manager dynamically selects agents based on context, enforces: │
│ • Max rounds (default: 15)                                     │
│ • Stall detection (3 consecutive stalled iterations)           │
│ • Human-in-loop pause (if missing_documents != [])            │
│ → Updates: risk_score, fraud_indicators, data_complete         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Phase 3: Handoff Decision (Human-in-Loop)                      │
├─────────────────────────────────────────────────────────────────┤
│ 1. AssessmentAgent: Synthesizes brief from specialist findings │
│ 2. ClaimsOfficer: Captures human approval/denial decision      │
│ 3. HandoffAgent: Packages settlement or denial payload         │
│ → Updates: agent_decision, handoff_status, payload ready       │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites
- Python 3.11+
- Azure OpenAI deployment with `gpt-4o` or similar model
- uv package manager (recommended) or pip

### Setup with uv

```powershell
# Clone repository (if not already done)
cd c:\Users\jomedin\Documents\claims-orchestration

# Create virtual environment
uv venv

# Activate environment
.venv\Scripts\Activate.ps1

# Install dependencies
uv pip install -r requirements.txt

# Install in editable mode
uv pip install -e platforms/semantic-kernel
```

### Environment Configuration

Create `.env` in workspace root:

```bash
# Azure OpenAI (required)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01

# Observability (optional)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_SERVICE_NAME=claims-orchestrator
ASPIRE_ALLOW_UNSECURED_TRANSPORT=1

# Orchestration tuning (optional)
ORCHESTRATION_MAX_ROUNDS=15
ORCHESTRATION_STALL_THRESHOLD=3
ORCHESTRATION_ENABLE_HITL=true
LOG_LEVEL=INFO
```

## Usage

### CLI Commands

#### Process New Claim

Process a claim submission with **interactive document collection**:

```powershell
# Interactive mode (default) - prompts for missing documents
python -m claims_sk.cli process shared/submission/claim_submission.md

# With output directory
python -m claims_sk.cli process shared/submission/claim_submission.md -o ./output

# Non-interactive mode - pauses without prompting
python -m claims_sk.cli process shared/submission/claim_submission.md --no-interactive

# Verbose logging
python -m claims_sk.cli process claim.md -v
```

**Interactive Flow**: When documents are missing, the CLI will:
1. List required documents
2. Ask if you want to provide them now
3. Prompt for file/directory paths
4. Validate and resume processing automatically

**Example:**
```
⚠ Missing Documents Detected
  1. vehicle_damage_photos
  2. insurance_exchange_form

Would you like to provide these documents now? [Y/n]: y

Path for 'vehicle_damage_photos': ./photos/
  ✓ Found 3 files in directory
Path for 'insurance_exchange_form': ./forms/exchange.pdf
  ✓ File found: exchange.pdf

Resuming orchestration...
```

See [Interactive Documents Guide](docs/INTERACTIVE_DOCUMENTS.md) for complete details.

#### Resume Paused Claim

Resume a paused claim after providing missing documents:

```powershell
# Resume with additional documents
python -m claims_sk.cli resume CLM-1120105522 -d ./additional_docs

# Resume with output directory
python -m claims_sk.cli resume CLM-1120105522 -d ./additional_docs -o ./output

# Resume with verbose logging
python -m claims_sk.cli resume CLM-1120105522 -d ./additional_docs -v
```

**Required**: The claim must have been previously paused with saved session in `sessions/{claim_id}/`.

#### List Saved Sessions

View all saved claim sessions:

```powershell
python -m claims_sk.cli list-sessions
```

Displays table with claim IDs, status, message counts, and timestamps.

#### Version Info

```powershell
python -m claims_sk.cli version
```

## Programmatic API

### Basic Usage

```python
import asyncio
from pathlib import Path
from claims_sk import create_runtime

async def process_claim():
    # Bootstrap runtime
    runtime = await create_runtime()
    
    # Get orchestrator
    orchestrator = runtime.get_orchestrator()
    
    # Process claim
    claim_data = {
        "claim_id": "CLM-2025-00001",
        "customer_id": "CUST-1234",
        "policy_number": "AUTO-789456",
        "incident_date": "2025-11-10",
        "claim_amount": 12000,
        "claim_type": "auto_collision",
    }
    
    result = await orchestrator.process_claim(claim_data)
    
    print(f"Status: {result['status']}")
    print(f"Termination: {result['termination_reason']}")
    
    if result.get("handoff_payload"):
        print(f"Handoff payload: {result['handoff_payload']}")

asyncio.run(process_claim())
```

### Session Persistence (Pause/Resume)

```python
# Submit new claim
result = await orchestrator.process_claim(claim_data)

if result["status"] == "paused":
    # Claim requires additional documents
    missing_docs = result["missing_documents"]
    print(f"Missing: {missing_docs}")
    
    # Later, resume with additional documents
    result = await orchestrator.continue_claim(
        claim_id="CLM-2025-00001",
        additional_documents={
            "documents": [
                {"type": "vehicle_damage_photos", "filename": "damage.jpg"},
                {"type": "insurance_exchange_form", "filename": "exchange.pdf"},
            ]
        },
    )
    
    print(f"Resumed status: {result['status']}")
```

See [Session Persistence Documentation](docs/SESSION_PERSISTENCE.md) for complete details.

### Backend API Integration

```python
from claims_sk.runtime import create_runtime

# Initialize service (at startup)
runtime = await create_runtime()
orchestrator = runtime.get_orchestrator()

# API endpoint: POST /claims
async def submit_claim(claim_data: dict):
    result = await orchestrator.process_claim(claim_data)
    return {
        "claim_id": claim_data["claim_id"],
        "status": result["status"],
        "missing_documents": result.get("missing_documents", []),
    }

# API endpoint: POST /claims/{claim_id}/continue
async def continue_claim(claim_id: str, documents: dict):
    result = await orchestrator.continue_claim(
        claim_id=claim_id,
        additional_documents=documents,
    )
    return {"status": result["status"]}
```

See [Backend API Example](examples/backend_api_example.py) for complete implementation.

### With Observability

```python
from claims_sk import create_runtime

async def process_with_telemetry():
    # Bootstrap with observability enabled via .env:
    # OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    
    runtime = await create_runtime()
    orchestrator = runtime.get_orchestrator()
    result = await orchestrator.process_claim(claim_data)
    
    return result
```

## Configuration

### Agent Configuration (`config/agents_config.yaml`)

Defines specialist agents for the three-phase workflow. A default configuration is auto-generated on first run with `test-agents` command.

### Orchestration Configuration

Tune termination policies via environment variables or runtime config:

```python
runtime = await create_runtime()
runtime.config["orchestration"] = {
    "max_rounds": 20,              # Increase for complex claims
    "stall_threshold": 5,           # More tolerance for stalls
    "enable_human_in_loop": True,   # Require operator approval
}
```

## Observability

### Aspire Dashboard Integration

Start Aspire Dashboard:

```powershell
dotnet aspire dashboard --open false
```

Dashboard available at: `http://localhost:18888`

### Emitted Telemetry

**Spans** (BPMN-aligned):
- `phase1_sequential_intake`
- `phase2_magentic_gathering`
- `phase3_handoff_decision`

**Span Attributes**:
- `claim.id`: Claim identifier
- `claim.ack_sent`: Acknowledgment status
- `claim.agent_decision`: Final decision
- `claim.handoff_status`: Settlement readiness
- `bpmn.state`: Current BPMN state
- `orchestration.status`: Final status
- `orchestration.termination_reason`: Why orchestration ended
- `orchestration.rounds`: Iterations executed

**Metrics**:
- `claims.processed{status}`: Total claims by status
- `claims.approved`: Approved claims counter
- `claims.denied`: Denied claims counter
- `orchestration.duration`: Duration histogram (seconds)
- `orchestration.rounds`: Rounds histogram
- `claims.risk_score`: Risk score distribution

## Termination Policies

The `ClaimsMagenticManager` implements BPMN-aligned termination conditions:

| Condition | Metadata Check | BPMN Node |
|-----------|---------------|-----------|
| **Approved** | `agent_decision == "approve"` AND `handoff_status == "ready_for_settlement"` | Approved – Ready for Settlement Handoff |
| **Denied (Manual)** | `agent_decision == "deny"` AND `denial_package_ready == True` | Denied |
| **Denied (SLA Breach)** | `sla_breached == True` | Denied |
| **Stalled** | Same agent loops ≥3 times with no progress | N/A |
| **Max Rounds** | `round_count >= max_rounds` (default: 15) | N/A |
| **Human-in-Loop** | `missing_documents != []` AND `enable_human_in_loop` | (Pause, not terminal) |

## Project Structure

```
platforms/semantic-kernel/
├── src/claims_sk/
│   ├── __init__.py           # Public API exports
│   ├── orchestration.py      # ClaimsOrchestrator + three-phase workflow
│   ├── managers.py           # ClaimsMagenticManager + termination logic
│   ├── agents.py             # AgentFactory + config loader
│   ├── runtime.py            # CoreRuntime bootstrap helper
│   ├── cli.py                # Typer CLI entry point
│   ├── observability.py      # OpenTelemetry + Aspire integration
│   └── tools/                # Tool plugins (TODO)
│       ├── policy_tools.py
│       ├── fraud_tools.py
│       ├── history_tools.py
│       └── mocks/            # Mock data adapters
├── config/
│   └── agents_config.yaml    # Agent definitions
├── tests/                     # Unit tests
├── README.md                  # This file
└── pyproject.toml             # Package metadata

shared/                        # Shared across all platforms
├── config/
│   ├── handoff_schema.json   # Settlement payload schema
│   ├── policy_rules.yaml
│   └── validation_checklist.yaml
├── datasets/                  # CSV data files
│   ├── policies.csv
│   ├── claims_history.csv
│   └── vendors.csv
└── submission/                # Canonical test fixture
    ├── claim_submission.md
    └── documents/
```

## Frontend Integration

The orchestration is designed to be consumed by a frontend application:

### REST API Endpoint (Future Work)

```python
from fastapi import FastAPI
from claims_sk import create_runtime

app = FastAPI()
runtime = None

@app.on_event("startup")
async def startup():
    global runtime
    runtime = await create_runtime()

@app.post("/api/claims/process")
async def process_claim(claim_data: dict):
    orchestrator = runtime.get_orchestrator()
    result = await orchestrator.process_claim(claim_data)
    
    return {
        "claim_id": result["context"]["claim_id"],
        "status": result["status"],
        "handoff_payload": result.get("handoff_payload"),
    }
```

### Handoff Payload Schema

The orchestration emits a standardized payload per `shared/config/handoff_schema.json`:

```json
{
  "claim_id": "CLM-2025-00001",
  "decision": "approve",
  "payout_amount": 12000,
  "agent_id": "AGT-001",
  "decision_timestamp": "2025-11-15T10:30:00Z",
  "confidence_score": 85,
  "fraud_risk": 15,
  "rationale": "Policy valid, no fraud indicators, reasonable estimate",
  "attachments": ["police_report.pdf", "estimate.pdf"]
}
```

## Development

### Running Tests

```powershell
pytest platforms/semantic-kernel/tests/ -v
```

### Type Checking

```powershell
mypy platforms/semantic-kernel/src/claims_sk
```

### Code Style

```powershell
black platforms/semantic-kernel/src/claims_sk
ruff check platforms/semantic-kernel/src/claims_sk
```

## Troubleshooting

### Common Issues

**Issue**: `ModuleNotFoundError: No module named 'semantic_kernel'`
- **Fix**: Ensure virtual environment is activated and dependencies installed:
  ```powershell
  .venv\Scripts\Activate.ps1
  uv pip install -r requirements.txt
  ```

**Issue**: `Missing required environment variables: ['AZURE_OPENAI_ENDPOINT']`
- **Fix**: Create `.env` file with Azure OpenAI credentials

**Issue**: `Agent config not found`
- **Fix**: Generate default config:
  ```powershell
  python -m claims_sk.cli test-agents
  ```

**Issue**: Observability not working (no traces in Aspire)
- **Fix**: Start Aspire Dashboard first, ensure `OTEL_EXPORTER_OTLP_ENDPOINT` is set:
  ```powershell
  dotnet aspire dashboard --open false
  $env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4317"
  ```

## References

- [Semantic Kernel Documentation](https://learn.microsoft.com/semantic-kernel/)
- [MagenticOrchestration Guide](https://learn.microsoft.com/semantic-kernel/agents/orchestration/magentic)
- [Azure OpenAI Service](https://learn.microsoft.com/azure/ai-services/openai/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
- [Aspire Dashboard](https://learn.microsoft.com/dotnet/aspire/fundamentals/dashboard/overview)

## Contributing

See [PLAN.md](../../PLAN.md) for the overall project architecture and design decisions.

## License

See [LICENSE](../../LICENSE) in repository root.

