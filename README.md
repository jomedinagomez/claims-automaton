# Claims Automaton

An AI-powered claims processing system using Semantic Kernel's multi-agent orchestration to assist insurance agents in efficiently assessing and deciding on insurance claims.

## Overview

This system provides an **agent-facing application** that leverages multiple AI agents to:
- Automatically gather and validate claim data from multiple sources
- Detect fraud indicators and assess risk
- Generate comprehensive assessment briefs for claims agents
- Capture agent decisions and hand off to settlement systems

**Key Features:**
- 🤖 Multi-agent orchestration using Semantic Kernel Magentic
- 👤 Human-in-the-loop: Agents make final decisions, not AI
- 📊 Real-time observability via OpenTelemetry + Aspire Dashboard
- ⚡ Fast local development with `uv` tooling
- 🔍 Comprehensive fraud detection and risk scoring
- 📋 BPMN-aligned workflow with explicit termination policies

## Architecture

### Agent Roster

| Agent | Purpose |
|-------|---------|
| **IntakeAgent** | Normalize intake data, detect missing fields |
| **DataSourcingAgent** | Query policy, claims history, and external feeds |
| **ValidationAgent** | Cross-check documents, run fraud heuristics |
| **AnalysisAgent** | Compute risk scores and impact assessments |
| **DecisionSupportAgent** | Generate agent-ready assessment briefs |
| **HandoffAgent** | Package decisions for settlement systems |
| **ReviewerAgent** | Quality-check AI outputs for compliance |

### Workflow

```
Customer Submits Claim
    ↓
Agent Receives in Queue
    ↓
System Auto-Gathers Data (Policy, History, External Signals)
    ↓
Data Complete? → No → Request Info / Agent Manual Entry
    ↓ Yes
AI Generates Assessment Brief
    ↓
Agent Reviews & Decides (Approve/Deny)
    ↓
System Emits Handoff Payload → Settlement Systems
```

See [BPMN Diagram](docs/general_insurance_payment_claim_process.bpmn) for detailed process flow.

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (fast Python package manager)
- Azure OpenAI access (endpoint + API key)
- [.NET Aspire Dashboard](https://learn.microsoft.com/en-us/dotnet/aspire/fundamentals/dashboard/overview) (optional, for observability)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/claims-orchestration.git
cd claims-orchestration

# Create virtual environment and install dependencies
uv venv
uv pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your Azure OpenAI credentials
```

### Configuration

Edit `.env` file:

```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# Observability (optional)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_SERVICE_NAME=claims-orchestrator
ASPIRE_ALLOW_UNSECURED_TRANSPORT=1
```

### Run a Test Claim (coming soon)

The Semantic Kernel CLI is being relocated into `platforms/semantic-kernel`. Once the migration finishes you will be able to process the canonical claim with:

```bash
uv run python -m claims_sk.cli --claim shared/submission/claim_submission.md
```

### Run with Observability (coming soon)

OpenTelemetry + Aspire wiring will return after the CLI move. The workflow will remain the same (Aspire dashboard on terminal 1, CLI execution targeting `claims_sk` on terminal 2) but the command will point at the Semantic Kernel backend package.

## Project Structure

```
claims-orchestration/
├── README.md
├── PLAN.md
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── docs/
│   ├── general_insurance_payment_claim_process.bpmn
│   └── general_insurance_payment_claim_process.jpg
├── shared/                     # Canonical datasets, configs, and submission assets
│   ├── README.md
│   ├── config/
│   ├── datasets/
│   └── submission/
├── platforms/
│   ├── semantic-kernel/
│   │   ├── README.md
│   │   ├── src/claims_sk/
│   │   └── tests/
│   ├── agent-framework/
│   │   └── README.md
│   └── azure-ai-foundry/
│       └── README.md
├── frontend/                   # Backend-agnostic UI surface
│   └── README.md
├── scripts/
│   └── validate_test_documents.py
└── shared utilities/config files referenced throughout
```

Each backend under `platforms/` is expected to import from `shared/` rather than copying files. The Semantic Kernel implementation currently owns the legacy Python code and will be the first fully wired backend; the Agent Framework and Azure AI Foundry folders are staged for upcoming work. The frontend directory is a placeholder for the claims-agent UI that will target all backends via a simple adapter.

## Testing

Each backend hosts its own pytest suite under `platforms/<name>/tests/`. Once the Semantic Kernel migration lands you will be able to run:

```bash
uv run pytest platforms/semantic-kernel/tests
```

Add per-backend test commands as additional implementations come online.

## FastAPI Service (Python-first UI Backend)

A lightweight FastAPI surface now wraps the Semantic Kernel orchestrator so Python teams can build HTMX/Alpine or template-driven front ends without touching JavaScript-heavy stacks.

### Start the API

```pwsh
cd frontend
# Install dependencies (once per environment)
uv pip install fastapi "uvicorn[standard]"

# Launch the service (requires ../.env Azure OpenAI settings)
uv run uvicorn api.main:app --reload
```

The server boots the same runtime used by the CLI, so ensure your `.env` is populated with Azure OpenAI credentials before starting. Once running you can interact with:

- `POST /claims/process` – submit a JSON payload identical to the CLI `claim_data` structure.
- `POST /claims/{claim_id}/resume` – supply `documents` and/or inline `notes` to resume paused claims.
- `GET /healthz` – readiness probe for container orchestrators.

Because the orchestrator still performs long-running Azure OpenAI calls, front-end clients should poll the response or use background workers/queues as you expand the surface.

## Development Workflow

1. **Tweak shared configs** in `shared/config/` (policy rules, validation checklist, handoff schema).
2. **Refresh datasets** or run generators inside `shared/datasets/generation_scripts/` as needed.
3. **Validate documents** with `python scripts/validate_test_documents.py --documents shared/submission/documents`.
4. **Modify backend code** under `platforms/<name>/src/` (Semantic Kernel is leading).
5. **Execute backend-specific tests** in `platforms/<name>/tests/` before wiring up observability or UI layers.

## Data Files

All reference assets now live under `shared/`. Backends should import them directly instead of copying files into platform-specific folders.

### Reference Data (CSV)
These simulate database exports for local testing and are stored in `shared/datasets/`:
- **policies.csv** - Active customer policies
- **claims_history.csv** - Historical claims data
- **vendors.csv** - Approved repair shops and medical providers
- **blacklist.csv** - Fraud watchlist

### Submission Package (Markdown)
Located in `shared/submission/`. Realistic claim submission scenarios for testing:
- **claim_submission.md** - Email-style auto collision claim submission from customer John Smith
  - Rear-end collision on I-95 with detailed incident narrative, vehicle/injury details, and witness information
  - References 4 supporting documents: police report, repair estimate, medical receipt, witness statement
  - Demonstrates realistic unstructured input that IntakeAgent must parse and normalize
  - Tests AI extraction of claim_id, policy_number, incident details, and document references
    - Supporting uploads: all markdown files under `shared/submission/documents/`

### Supporting Documents
Stored in `shared/submission/documents/`, these markdown files correspond one-to-one with the references inside `claim_submission.md` and are treated as the canonical extracted text for customer uploads.

## Data Generation Pipeline

All dataset scripts live under `shared/datasets/generation_scripts/`. Every generator now requires a valid Azure OpenAI deployment (no synthetic fallback paths). Missing credentials or model failures will surface as hard errors so you never unknowingly mix placeholder data into analyses.

### Azure OpenAI configuration for generators

Set the standard connection variables in `.env`:

```
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

To switch the generators to GPT-5.1 reasoning (or any reasoning-capable model), add:

```
# Optional, only when targeting reasoning models
AZURE_OPENAI_REASONING_DEPLOYMENT=gpt-5.1
AZURE_OPENAI_USE_REASONING=true
AZURE_OPENAI_REASONING_EFFORT=medium  # low|medium|high
AZURE_OPENAI_MAX_OUTPUT_TOKENS=4096   # adjust as needed for schema size
```

When reasoning is enabled the scripts automatically drop temperature/top-p, instead sending `reasoning.effort` and `max_output_tokens`. Leave the variables unset (or `AZURE_OPENAI_USE_REASONING=false`) to keep using the standard chat deployment and, optionally, override creativity globally via `AZURE_OPENAI_TEMPERATURE`.

Use the phased orchestrator to control how much data you generate at once:

```bash
# Run the entire pipeline
python shared/datasets/generation_scripts/generate_all_claims_data.py

# Generate only the foundational policy/vendor assets
python shared/datasets/generation_scripts/generate_all_claims_data.py --phase policies --policies 250

# After reviewing the base data, add claims + payout benchmarks
python shared/datasets/generation_scripts/generate_all_claims_data.py --phase claims --claims 150

# Skip an individual step (quote multi-word labels)
python shared/datasets/generation_scripts/generate_all_claims_data.py --phase policies --skip-phase "Coverage Matrix"

# Enforce the PLAN.md record counts
python shared/datasets/generation_scripts/generate_all_claims_data.py --strict-plan
```

Running the `claims` phase expects an up-to-date `shared/datasets/policies.csv`. Generate or supply that file first before producing claims history or payout benchmarks.

Each Azure-backed generator now issues multiple smaller LLM requests (policies ≈20 records/batch, vendors & blacklist ≈25, claims ≈30). This keeps GPT-5.1 reasoning runs well within token limits while preserving deterministic seeds—the scripts automatically advance the seed per batch so retries remain reproducible.

The prompts for policies, vendors, blacklist, and claims now embed the same level of operational guidance as the original insurance lab reference scripts (distribution targets, audit rules, compassionate claims handling, etc.), so GPT-5.1 receives explicit business requirements without you having to tweak the code each run.

### Customer Documents (Markdown)
Simulated PDF text extraction (all correspond to `claim_submission.md` - CLM-2025-00142):
- **police_report_12345.md** - Maryland State Police report #2025-PD-8821, rear-end collision on I-95
- **repair_estimate_001.md** - Honest Auto Body estimate $2,850.22 (approved vendor VND-001)
- **medical_receipt_summary.md** - Metro Orthopedic cervical strain treatment $515
- **witness_statement.txt** - Michael Johnson witness corroboration

These fixtures are intentionally rich in detail (names, addresses, invoices) but remain 100% synthetic—no real customers, vendors, or providers are referenced. Run the validator anytime you edit files under `shared/submission/documents` to ensure they still honor the MD/VA/DC/PA-only rule set and license formats:

```bash
python scripts/validate_test_documents.py --documents shared/submission/documents
```

## Key Technologies

- **[Semantic Kernel](https://github.com/microsoft/semantic-kernel)** - AI orchestration framework
- **[Magentic Pattern](https://learn.microsoft.com/en-us/semantic-kernel/agents/)** - Multi-agent coordination
- **[OpenTelemetry](https://opentelemetry.io/)** - Distributed tracing
- **[.NET Aspire](https://learn.microsoft.com/en-us/dotnet/aspire/)** - Local observability dashboard
- **[uv](https://github.com/astral-sh/uv)** - Fast Python package management
- **[Pydantic](https://docs.pydantic.dev/)** - Data validation

## Documentation

- [PLAN.md](PLAN.md) - Complete architecture and implementation plan
- [BPMN Process](docs/general_insurance_payment_claim_process.bpmn) - Visual workflow diagram
- [API Documentation](docs/api.md) - REST API specification (coming soon)
- [Shared assets](shared/README.md) - Canonical datasets, fixtures, and configs consumed by every platform

## Roadmap

- [x] BPMN workflow design
- [x] Reference data schemas
- [x] Test fixtures and documents
- [ ] Agent implementations
- [ ] Mock API layer
- [ ] Orchestration engine
- [ ] Termination policies
- [ ] CLI interface
- [ ] REST API for front-end
- [ ] Front-end UI
- [ ] Database integration
- [ ] External API integrations
- [ ] Production deployment

## Contributing

This is a reference implementation for educational purposes. For production use, consider:
- Replace mock APIs with real database connections
- Implement proper authentication/authorization
- Add comprehensive error handling
- Set up CI/CD pipelines
- Configure production observability (Application Insights, etc.)

## License

MIT License - See [LICENSE](LICENSE) file for details

## Contact

For questions or feedback, please open an issue in this repository.
