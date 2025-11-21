#!/usr/bin/env python3
"""Phased orchestrator for all claims reference datasets."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple

SCRIPTS = Path(__file__).parent
DATA_ROOT = SCRIPTS.parent

CONFIG_FILES = {
    DATA_ROOT / "risk" / "fraud_indicators.yaml": dedent(
        """
        patterns:
          duplicate_claims:
            threshold: 2
            timeframe_days: 90
            severity: high
            description: "Multiple claims for same incident type within 90 days"
          high_value_claim:
            threshold: 50000
            severity: medium
            description: "Claim amount exceeds $50k requires additional review"
          blacklisted_entity:
            severity: critical
            description: "Customer, provider, or shop on blacklist"
          inconsistent_statements:
            severity: high
            description: "Conflicting dates, locations, or narratives in documentation"
          suspicious_timing:
            patterns:
              - "Policy activated <30 days before incident"
              - "Claim filed >14 days after incident without explanation"
            severity: medium
          missing_corroboration:
            severity: medium
            description: "No police report, witness, or third-party verification"
        """
    ).strip()
    + "\n",
    DATA_ROOT / "risk" / "risk_scoring_rules.json": dedent(
        """
        {
          "risk_factors": [
            {
              "factor": "customer_claims_history",
              "ranges": [
                {"min": 0, "max": 0, "points": 0, "label": "no_history"},
                {"min": 1, "max": 2, "points": 10, "label": "low_frequency"},
                {"min": 3, "max": 5, "points": 25, "label": "moderate_frequency"},
                {"min": 6, "max": 999, "points": 50, "label": "high_frequency"}
              ]
            },
            {
              "factor": "claim_amount_ratio",
              "description": "Ratio of claim to policy coverage limit",
              "ranges": [
                {"min": 0.0, "max": 0.25, "points": 0, "label": "low"},
                {"min": 0.25, "max": 0.50, "points": 5, "label": "moderate"},
                {"min": 0.50, "max": 0.75, "points": 15, "label": "high"},
                {"min": 0.75, "max": 1.0, "points": 30, "label": "very_high"}
              ]
            },
            {
              "factor": "documentation_completeness",
              "ranges": [
                {"min": 90, "max": 100, "points": -10, "label": "complete"},
                {"min": 70, "max": 89, "points": 5, "label": "mostly_complete"},
                {"min": 50, "max": 69, "points": 15, "label": "incomplete"},
                {"min": 0, "max": 49, "points": 30, "label": "severely_incomplete"}
              ]
            }
          ],
          "score_interpretation": [
            {"min": 0, "max": 20, "risk_level": "low", "recommendation": "approve"},
            {"min": 21, "max": 50, "risk_level": "medium", "recommendation": "review"},
            {"min": 51, "max": 100, "risk_level": "high", "recommendation": "deny"}
          ]
        }
        """
    ).strip()
    + "\n",
    DATA_ROOT / "external" / "weather_events.json": dedent(
        """
        {
          "events": [
            {
              "event_id": "WX-2025-11-10-001",
              "date": "2025-11-10",
              "location": "I-95 Corridor, Maryland",
              "event_type": "heavy_rain",
              "severity": "moderate",
              "description": "Persistent rain 2-4 inches, reduced visibility",
              "verified_sources": ["NOAA", "local_news"]
            },
            {
              "event_id": "WX-2025-09-15-002",
              "date": "2025-09-15",
              "location": "Houston, TX",
              "event_type": "hail",
              "severity": "severe",
              "description": "Golf ball sized hail, widespread vehicle damage",
              "verified_sources": ["NOAA", "insurance_industry_cat"]
            }
          ]
        }
        """
    ).strip()
    + "\n",
    DATA_ROOT / "external" / "police_reports.json": dedent(
        """
        {
          "reports": [
            {
              "report_number": "2025-PD-8821",
              "incident_date": "2025-11-10",
              "location": "I-95 Northbound, Mile Marker 42",
              "incident_type": "vehicle_collision",
              "parties": [
                {"name": "John Smith", "role": "victim", "vehicle": "Toyota Camry"},
                {"name": "Jane Doe", "role": "at_fault", "vehicle": "Honda Accord"}
              ],
              "narrative": "Vehicle 2 failed to stop at red light, rear-ended Vehicle 1",
              "verified": true,
              "officer_badge": "12345"
            }
          ]
        }
        """
    ).strip()
    + "\n",
}


STEPS: List[Dict[str, Any]] = [
  {
    "key": "policies",
    "phase": "policies",
    "label": "Policies",
    "command": [sys.executable, "01_generate_policies.py"],
    "output": DATA_ROOT / "policies.csv",
    "default_records": 1000,
    "plan_range": (1000, 1000),
    "depends_on": [],
  },
  {
    "key": "vendors",
    "phase": "policies",
    "label": "Vendors",
    "command": [sys.executable, "02_generate_vendors.py"],
    "output": DATA_ROOT / "vendors.csv",
    "default_records": 100,
    "plan_range": (100, 100),
    "depends_on": [],
  },
  {
    "key": "blacklist",
    "phase": "policies",
    "label": "Blacklist",
    "command": [sys.executable, "03_generate_blacklist.py"],
    "output": DATA_ROOT / "risk" / "blacklist.csv",
    "default_records": 50,
    "plan_range": (50, 50),
    "depends_on": ["Vendors"],
  },
  {
    "key": "coverage",
    "phase": "policies",
    "label": "Coverage Matrix",
    "command": [sys.executable, "04_generate_coverage_matrix.py"],
    "output": DATA_ROOT / "coverage_matrix.csv",
    "plan_range": (12, 12),
    "depends_on": [],
  },
  {
    "key": "medical_codes",
    "phase": "policies",
    "label": "Medical Codes",
    "command": [sys.executable, "05_generate_medical_codes.py"],
    "output": DATA_ROOT / "external" / "medical_codes.csv",
    "plan_range": (50, 100),
    "depends_on": [],
  },
  {
    "key": "claims",
    "phase": "claims",
    "label": "Claims History",
    "command": [sys.executable, "06_generate_claims_history.py"],
    "output": DATA_ROOT / "historical" / "claims_history.csv",
    "default_records": 350,
    "plan_range": (300, 400),
    "depends_on": ["Policies"],
  },
  {
    "key": "payouts",
    "phase": "claims",
    "label": "Payout Benchmarks",
    "command": [sys.executable, "07_generate_payout_benchmarks.py"],
    "output": DATA_ROOT / "historical" / "payout_benchmarks.csv",
    "plan_range": (12, 12),
    "depends_on": ["Claims History"],
  },
]

STEP_MAP = {step["label"]: step for step in STEPS}


def count_csv_records(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return 0
        return sum(1 for _ in reader)


def describe_plan_range(spec: Dict[str, Any]) -> str:
    plan_range: Tuple[int | None, int | None] | None = spec.get("plan_range")
    if not plan_range:
        return "n/a"
    low, high = plan_range
    if low is not None and high is not None:
        if low == high:
            return f"{low:,}"
        return f"{low:,}-{high:,}"
    if low is not None:
        return f">={low:,}"
    if high is not None:
        return f"<={high:,}"
    return "n/a"


def enforce_plan(records: int, spec: Dict[str, Any], strict_plan: bool) -> None:
    plan_range: Tuple[int | None, int | None] | None = spec.get("plan_range")
    if not plan_range:
        return
    low, high = plan_range
    too_low = low is not None and records < low
    too_high = high is not None and records > high
    if not (too_low or too_high):
        return
    plan_desc = describe_plan_range(spec)
    message = f"{spec['label']} produced {records} records, plan target {plan_desc}"
    if strict_plan:
        raise RuntimeError(message)
    print(f"WARNING: {message}")


  def plan_satisfied(records: Optional[int], spec: Dict[str, Any]) -> bool:
    if records is None:
      return spec.get("plan_range") is None
    plan_range: Tuple[int | None, int | None] | None = spec.get("plan_range")
    if not plan_range:
      return True
    low, high = plan_range
    if low is not None and records < low:
      return False
    if high is not None and records > high:
      return False
    return True


def verify_output(label: str, path: Path, strict_plan: bool) -> dict[str, str | int]:
  if not path.exists():
    raise RuntimeError(f"{label} expected output missing: {path}")
  records = count_csv_records(path) if path.suffix == ".csv" else None
  if records is not None:
    print(f"{label} output verified -> {records} records at {path.relative_to(DATA_ROOT)}")
  else:
    print(f"{label} output verified -> {path.relative_to(DATA_ROOT)}")
  if records is not None:
    spec = STEP_MAP.get(label)
    if spec:
      enforce_plan(records, spec, strict_plan)
  return {"label": label, "path": str(path.relative_to(DATA_ROOT)), "records": records or 0}


def run_step(step: Dict[str, Any], overrides: Dict[str, List[str]], strict_plan: bool) -> dict[str, str | int]:
  label = step["label"]  # type: ignore[index]
  command = list(step["command"])  # type: ignore[index]
  command += overrides.get(label, [])
  print(f"\n=== {label} ===")
  try:
    subprocess.run(command, cwd=SCRIPTS, check=True)
  except subprocess.CalledProcessError as exc:  # pragma: no cover - surfaced to user
    raise RuntimeError(f"{label} failed with exit code {exc.returncode}") from exc
  print(f"{label} complete")
  return verify_output(label, step["output"], strict_plan)  # type: ignore[arg-type]


def write_config_files() -> None:
    for path, contents in CONFIG_FILES.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        print(f"Wrote {path.relative_to(DATA_ROOT)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all data generation phases")
    parser.add_argument(
        "--skip-phase",
        action="append",
        default=[],
        help="Optional phase labels to skip (e.g., 'Vendors')",
    )
    parser.add_argument(
        "--policies",
        type=int,
        default=1000,
        help="Number of policy records to generate",
    )
    parser.add_argument(
        "--claims",
        type=int,
        default=350,
        help="Number of claims to generate",
    )
    parser.add_argument(
        "--vendors",
        type=int,
        default=100,
        help="Number of vendor records to generate",
    )
    parser.add_argument(
        "--blacklist",
        type=int,
        default=50,
        help="Number of blacklist entries to generate",
    )
    parser.add_argument(
      "--strict-plan",
      action="store_true",
      help="Fail if any dataset falls outside the PLAN.md record targets",
    )
    parser.add_argument(
        "--phase",
        choices=["all", "policies", "claims"],
        default="all",
        help="Run only a portion of the pipeline (policies foundation, claims, or all phases)",
    )
    parser.add_argument(
      "--only-missing",
      action="store_true",
      help="Skip steps whose outputs already exist and satisfy PLAN targets",
    )
    return parser.parse_args()


def select_steps(selected_phase: str, skip: List[str]) -> List[Dict[str, Any]]:
    steps = [
        step
        for step in STEPS
        if selected_phase == "all" or step["phase"] == selected_phase
    ]
    filtered = [step for step in steps if step["label"] not in skip]
    if not filtered:
        raise RuntimeError("No phases selected after applying filters")
    return filtered


def filter_completed_steps(steps: List[Dict[str, Any]], only_missing: bool) -> List[Dict[str, Any]]:
  if not only_missing:
    return steps

  remaining: List[Dict[str, Any]] = []
  for step in steps:
    path: Path = step["output"]  # type: ignore[assignment]
    label = step["label"]
    spec = STEP_MAP.get(label, {})

    if not path.exists():
      remaining.append(step)
      continue

    records: Optional[int]
    if path.suffix == ".csv":
      records = count_csv_records(path)
    else:
      records = None

    if plan_satisfied(records, spec):
      desc = f"{records} records" if records is not None else "existing output"
      print(f"Skipping {label} (already satisfied: {desc} -> {path.relative_to(DATA_ROOT)})")
      continue

    print(f"Re-running {label}; existing output does not meet PLAN targets")
    remaining.append(step)

  if not remaining:
    raise RuntimeError("All selected steps already satisfy PLAN targets; nothing to run")

  return remaining


def ensure_phase_prereqs(steps: List[Dict[str, Any]]) -> None:
    completed: List[str] = []
    for step in steps:
        required = step.get("depends_on", [])
        missing = [dep for dep in required if dep not in completed]
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(
                f"{step['label']} requires {joined} to run first. Adjust --phase/--skip options."
            )
        completed.append(step["label"])  # type: ignore[index]


def main() -> None:
    args = parse_args()
    overrides = {
        "Policies": ["--records", str(args.policies)],
        "Vendors": ["--records", str(args.vendors)],
        "Blacklist": ["--records", str(args.blacklist)],
        "Claims History": ["--records", str(args.claims)],
    }

    try:
        steps = filter_completed_steps(select_steps(args.phase, args.skip_phase), args.only_missing)
        ensure_phase_prereqs(steps)
        results: List[Dict[str, str | int]] = []
        for step in steps:
            results.append(run_step(step, overrides, args.strict_plan))

        write_config_files()
        print("\nPhase run summary (PLAN targets in parentheses):")
        for result in results:
            label = result["label"]
            records = result["records"]
            path = result["path"]
            spec = STEP_MAP.get(label, {})
            plan_desc = describe_plan_range(spec)
            print(f" - {label}: {records} records (plan {plan_desc}) -> {path}")
        print("\nRequested phases complete. Outputs located under", DATA_ROOT)
    except RuntimeError as exc:  # pragma: no cover
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
