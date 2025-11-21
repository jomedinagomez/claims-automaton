#!/usr/bin/env python3
"""Generate claims_history.csv referencing policies.csv via Azure OpenAI."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from textwrap import dedent
from typing import Iterable, List, Literal, Optional
import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from azure_llm import (
    AzureOpenAI,
    build_azure_client,
    build_response_kwargs,
    extract_response_text,
    fix_schema_for_azure,
)

ClaimStatus = Literal["closed_approved", "closed_denied", "open"]
ClaimType = Literal["auto_collision", "auto_comprehensive", "home_fire", "health_surgery"]


class ClaimRecord(BaseModel):
    claim_id: str = Field(..., pattern=r"^CLM-20\d{2}-\d{5}$")
    customer_id: str = Field(..., pattern=r"^CUST-\d{4}$")
    policy_number: str
    claim_type: ClaimType
    incident_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    filed_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    closed_date: str = Field(..., pattern=r"^(\d{4}-\d{2}-\d{2})?$")  # Required; empty string for open claims
    amount_requested: float
    reserved_amount: float
    amount_paid: float
    claim_status: ClaimStatus
    fraud_flag: bool
    assigned_adjuster: str = Field(..., pattern=r"^AGT-\d{3}$")
    processing_days: int
    notes: str


class ClaimBatch(BaseModel):
    claims: List[ClaimRecord]


DEFAULT_BATCH_SIZE = 20  # Larger batches improve throughput; lower this if Azure requests begin timing out
MAX_BATCH_RETRY_MULTIPLIER = 8  # Provide extra attempts when reasoning responses need retries

CLAIMS_GUIDANCE = dedent(
    """
    Claims portfolio targets:
    - Claim type mix: auto_collision 35%, auto_comprehensive 25%, home_fire 20%, health_surgery 20. Use coverage_matrix deductibles/limits in reasoning for notes.
    - Status mix: closed_approved 94%, closed_denied 3%, open 3%. Denied records must cite concrete reasons (policy lapse, documentation gaps, fraud findings). Open claims keep closed_date as empty string "" and processing_days aligned with current investigation stage.
    - Fraud flags around 5% overall, skewed toward repeat-vendor issues or blacklisted entities; mention trigger in notes.
    - When notes reference payouts or denials, echo the relevant coverage tier (core/enhanced) and cite the deductible or coverage cap pulled from the policy_sample's coverage_matrix entry.
    - Timeline realism: incident_date within last 24 months, filed_date within 14 days of incident for auto/home claims and within 3 days for health surgeries. closed_date typically 10-45 days after filed_date unless claim_status is open (then use empty string "").
    - Amount relationships: reserved_amount slightly above amount_paid for approved claims; amount_paid <= reserved_amount and within policy tier coverage. Reference policy deductibles/limits when describing payouts.
    - Fraud playbook: when fraud_flag is true, specify the investigative action taken (e.g., SIU referral, vendor audit hold, license verification) and document whether payouts remain on hold or partially released.
    - Cross-reference vendor or blacklist context when applicable and state if remediation steps (vendor suspension, extra inspection) are triggered so downstream teams can replicate the audit trail.
    - Assigned adjusters rotate AGT-### identifiers; reuse to simulate workload but keep consistent formatting.
    - Notes: 1 concise sentence referencing scene evidence, documentation, or payout decision—avoid boilerplate and redact sensitive medical details beyond procedure names.
    - Privacy + tone: keep descriptions neutral, customer-respectful, and compliant with HIPAA/PII expectations (no full addresses, no sensational language).
    - Always align claim_type, coverage, and geography with the provided policy_sample; never fabricate policy numbers or states outside MD/VA/DC/PA.
    """
).strip()


def sample_policies(df: pd.DataFrame, n: int = 25) -> List[dict]:
    return df.sample(min(len(df), n)).to_dict(orient="records")


def llm_generate(client: AzureOpenAI, count: int, seed: int, policies: List[dict], previous_batch: List[ClaimRecord] | None = None) -> List[ClaimRecord]:
    user_content = {
        "record_count": count,
        "seed": seed,
        "policy_sample": policies,
        "rules": {
            "status_distribution": {"closed_approved": 0.94, "closed_denied": 0.03, "open": 0.03},
            "fraud_flag_rate": 0.05,
        },
        "guidance": CLAIMS_GUIDANCE,
    }
    
    if previous_batch:
        total = len(previous_batch)
        
        # Calculate distributions
        claim_type_dist = {}
        status_dist = {}
        fraud_count = 0
        adjusters_used = set()
        amount_ranges = {"under_5k": 0, "5k_15k": 0, "15k_50k": 0, "over_50k": 0}
        
        for c in previous_batch:
            claim_type_dist[c.claim_type] = claim_type_dist.get(c.claim_type, 0) + 1
            status_dist[c.claim_status] = status_dist.get(c.claim_status, 0) + 1
            if c.fraud_flag:
                fraud_count += 1
            adjusters_used.add(c.assigned_adjuster)
            
            # Categorize amounts
            if c.amount_paid < 5000:
                amount_ranges["under_5k"] += 1
            elif c.amount_paid < 15000:
                amount_ranges["5k_15k"] += 1
            elif c.amount_paid < 50000:
                amount_ranges["15k_50k"] += 1
            else:
                amount_ranges["over_50k"] += 1
        
        analytics = {
            "total_generated": total,
            "claim_type_distribution": {k: f"{(v/total)*100:.1f}%" for k, v in claim_type_dist.items()},
            "status_distribution": {k: f"{(v/total)*100:.1f}%" for k, v in status_dist.items()},
            "fraud_rate": f"{(fraud_count/total)*100:.1f}%",
            "amount_distribution": {k: f"{(v/total)*100:.1f}%" for k, v in amount_ranges.items()},
            "unique_adjusters": len(adjusters_used),
            "adjusters_used": list(adjusters_used),
        }
        
        targets = {
            "claim_type_target": {"auto_collision": "35%", "auto_comprehensive": "25%", "home_fire": "20%", "health_surgery": "20%"},
            "status_target": {"closed_approved": "94%", "closed_denied": "3%", "open": "3%"},
            "fraud_target": "5%",
        }
        
        user_content["current_analytics"] = analytics
        user_content["target_distributions"] = targets
        user_content["steering_instruction"] = "Balance claim types and statuses to match targets. Create diverse incident scenarios and claim narratives. Vary adjusters (reuse some, add new ones). Mix low/medium/high value claims. Ensure interesting, varied claim stories with specific details."
    
    messages = [
        {
            "role": "system",
            "content": "Produce historical insurance claims referencing the provided policy sample.",
        },
        {
            "role": "user",
            "content": json.dumps(user_content),
        },
    ]
    response = client.chat.completions.create(
        **build_response_kwargs(
            messages=messages,
            schema=fix_schema_for_azure(ClaimBatch.model_json_schema()),
            seed=seed,
            temperature_default=0.6,
        )
    )
    payload = extract_response_text(response)
    return ClaimBatch.model_validate_json(payload).claims


def generate_dataset(
    client: AzureOpenAI,
    total_records: int,
    seed: int,
    policy_df: pd.DataFrame,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> List[ClaimRecord]:
    records: List[ClaimRecord] = []
    max_batches = max(1, math.ceil(total_records / batch_size))
    max_attempts = max_batches * MAX_BATCH_RETRY_MULTIPLIER
    attempt = 0

    while len(records) < total_records and attempt < max_attempts:
        attempt += 1
        target = min(batch_size, total_records - len(records))
        policy_context = sample_policies(policy_df)
        previous_batch = records if records else None
        print(
            (
                f"Claims batch {attempt} (aiming for {total_records} total): "
                f"requesting {target} records with {len(records)} collected..."
            ),
            flush=True,
        )
        try:
            claims = llm_generate(client, target, seed + attempt - 1, policy_context, previous_batch)
        except ValidationError as ex:
            raise RuntimeError(f"Azure OpenAI claims validation failed on batch {attempt}: {ex}") from ex
        except Exception as ex:  # pragma: no cover
            raise RuntimeError(f"Azure OpenAI claims generation failed on batch {attempt}: {ex}") from ex
        records.extend(claims)
        print(
            (
                f"Claims batch {attempt} complete -> {len(records)}/{total_records} records"
            ),
            flush=True,
        )

    if len(records) < total_records:
        raise RuntimeError(
            "Claims generation exhausted retry budget before hitting target. "
            f"Generated {len(records)} of {total_records} required records after {attempt} attempts."
        )

    return records[:total_records]


OUTPUT_COLUMNS = [
    "claim_id",
    "customer_id",
    "policy_number",
    "claim_type",
    "incident_date",
    "filed_date",
    "closed_date",
    "amount_requested",
    "reserved_amount",
    "amount_paid",
    "claim_status",
    "fraud_flag",
    "assigned_adjuster",
    "processing_days",
    "notes",
]


def write_csv(records: Iterable[ClaimRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.model_dump())


def print_claims_summary(records: List[ClaimRecord]) -> None:
    if not records:
        print("Claims summary -> no records generated")
        return
    total = len(records)
    type_counts = Counter(record.claim_type for record in records)
    status_counts = Counter(record.claim_status for record in records)
    fraud_rate = (sum(1 for record in records if record.fraud_flag) / total) * 100
    print(
        "Claims summary -> total: {total}, types [{types}], statuses [{statuses}], fraud_rate: {fraud:.1f}%".format(
            total=total,
            types=", ".join(f"{k}:{v}" for k, v in type_counts.most_common()),
            statuses=", ".join(f"{k}:{v}" for k, v in status_counts.most_common()),
            fraud=fraud_rate,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate claims_history.csv")
    parser.add_argument("--records", type=int, default=350)
    parser.add_argument("--seed", type=int, default=404)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Records per Azure OpenAI call",
    )
    parser.add_argument(
        "--policies",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "policies.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "historical" / "claims_history.csv",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    if not args.policies.exists():
        raise SystemExit(f"Policy file not found: {args.policies}")
    policy_df = pd.read_csv(args.policies)
    if policy_df.empty:
        raise SystemExit("Policy file is empty")

    try:
        print("Claims generator starting -> initializing Azure OpenAI client...", flush=True)
        client = build_azure_client()
        print("Claims generator ready -> beginning batch execution", flush=True)
        records = generate_dataset(client, args.records, args.seed, policy_df, args.batch_size)
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"Azure OpenAI generation failed: {exc}") from exc

    print_claims_summary(records)
    write_csv(records, args.output)
    print(f"Generated {len(records)} claims at {args.output}")


if __name__ == "__main__":
    main()
