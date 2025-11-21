# Shared Assets

Central hub for every dataset, configuration file, and validation artifact used by the implementations under `platforms/`.

## Contents
- `datasets/` – synthetic CSV/JSON assets that stand in for operational databases (policies, vendors, history, risk feeds).
- `config/` – reusable rules and schemas such as `policy_rules.yaml`, `validation_checklist.yaml`, and `handoff_schema.json`.
- `submission/` – end-to-end test scenario materials: `claim_submission.md` plus the supporting evidence in `submission/documents/`.

## Usage Guidelines
1. Treat every file in this directory as **authoritative**. Backend implementations should import/stream data directly from here rather than keeping private copies.
2. When a platform needs a derived view of a dataset, write the adapter/loader inside that platform and leave the shared asset intact.
3. If you add or change anything under `submission/`, update the validation scripts in `scripts/` so every backend benefits from the same guarantees.
