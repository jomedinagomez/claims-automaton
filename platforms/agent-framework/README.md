# Azure Agent Framework Backend

Placeholder for the Azure Agent Framework implementation. This backend will mirror the shared datasets/config files in `../../shared/` but build the orchestration using Azure's hosted Agent Framework runtime and connectors.

## Planned Responsibilities
- Host agent definitions, tools, and routing logic inside an Agent Framework project under `src/`.
- Provide unit and integration tests in `tests/` that read the canonical fixtures from `../../shared/`.
- Surface a REST layer or function app that the shared frontend can call just like the Semantic Kernel backend.

## Bootstrap Checklist
1. Initialize an Agent Framework workspace under `src/agent_framework_app/` (exact path TBD).
2. Create adapters that stream shared CSV/YAML files into whichever storage or memory format the framework expects.
3. Mirror the Magentic agent roster so feature parity stays consistent across backends.
