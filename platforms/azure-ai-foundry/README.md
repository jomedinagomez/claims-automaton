# Azure AI Foundry Backend

This backend will showcase the same claims orchestration experience but implemented with Azure AI Foundry (prompt flow, orchestration services, and managed connections).

## Planned Scope
- Store Prompt Flow (or follow-on) assets inside `src/` with automation scripts to publish flows to an Azure AI Foundry project.
- Keep tests alongside the flow definitions so we can validate them locally against the shared fixtures before deploying.
- Provide a simple HTTP front door (e.g., Azure Functions or Container Apps) so the frontend can switch between Foundry and the other backends by toggling a base URL.

## Immediate To-Dos
1. Decide on the exact Foundry artifact layout (Prompt Flow vs. Agents) and scaffold sample YAML.
2. Add scripts to sync shared policy/data files into the expected storage (Blob, Cosmos, etc.) or provide stub adapters during local runs.
3. Document how to provision the minimal Azure resources required so contributors can reproduce the setup.
