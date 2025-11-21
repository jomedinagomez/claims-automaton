#!/usr/bin/env python3
"""Claims orchestration policy portfolio generator.

This implementation requires Azure OpenAI structured output (Pydantic) for
realistic records. If the Azure client is unavailable or validation fails the
script will exit immediately so partial or synthetic data is never produced.
The output is a CSV located at shared/datasets/policies.csv by default.
"""

from __future__ import annotations

import argparse
import csv
import json
import json
import math
from collections import Counter
from pathlib import Path
from textwrap import dedent
from typing import Iterable, List, Literal, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from azure_llm import (
    AzureOpenAI,
    build_azure_client,
    build_response_kwargs,
    extract_response_text,
    fix_schema_for_azure,
)

# ----------------------------------------------------------------------------
# Pydantic Schemas for structured output
# ----------------------------------------------------------------------------

VehicleUsage = Literal["personal", "commuter", "commercial"]
PolicyStatus = Literal["active", "lapsed", "suspended", "cancelled"]
PaymentStatus = Literal["current", "overdue", "autopay", "grace"]


class PolicyRecord(BaseModel):
    policy_number: str = Field(..., pattern=r"^(AUTO|HOME|HEALTH)-\d{6}$")
    customer_id: str = Field(..., pattern=r"^CUST-\d{4}$")
    policy_holder_name: str
    dob: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    license_number: str
    license_state: Literal["MD", "VA", "DC", "PA"]
    policy_type: Literal["auto", "home", "health"]
    tier: Literal["basic", "standard", "premium"]
    status: PolicyStatus
    effective_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    expiration_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    annual_premium: float = Field(..., ge=400, le=6200)
    payment_status: PaymentStatus
    collision_limit: Optional[int]
    comprehensive_limit: Optional[int]
    deductible_collision: Optional[int]
    deductible_comprehensive: Optional[int]
    liability_bi_per_person: Optional[int]
    liability_bi_per_accident: Optional[int]
    liability_pd: Optional[int]
    uninsured_motorist: Optional[int]
    medical_payments: Optional[int]
    aggregate_limit_per_year: Optional[int]
    claims_count_this_year: int = Field(..., ge=0, le=5)
    claims_paid_this_year: int = Field(..., ge=0)
    remaining_aggregate: Optional[int]
    vehicle_make: Optional[str]
    vehicle_model: Optional[str]
    vehicle_year: Optional[int]
    vehicle_vin: Optional[str]
    vehicle_usage: Optional[VehicleUsage]
    garaging_address: str


class PolicyBatch(BaseModel):
    policies: List[PolicyRecord]


POLICY_GUIDANCE = dedent(
    """
    Dataset goals:
    - Geographic mix: ~30% MD, 30% VA, 25% PA, 15% DC; mirror regional weather/traffic risks in notes.
    - Policy mix: 60% auto, 25% home, 15% health. IMPORTANT: vehicle_* fields MUST be filled for auto policies; set to null for home/health.
    - Tier mix: basic 35%, standard 45%, premium 20. Tiers drive coverage/deductible levels (premium -> higher limits, lower deductibles).
    - Status mix: active 82%, lapsed 8%, suspended 5%, cancelled 5. Couple payment_status with status (e.g., overdue/grace for suspended or lapsed only).
    - Claim exposure: For AUTO policies, populate ALL of: collision_limit, comprehensive_limit, deductible_collision, deductible_comprehensive, liability_bi_per_person, liability_bi_per_accident, liability_pd, uninsured_motorist, medical_payments, aggregate_limit_per_year, and remaining_aggregate. For HOME policies, populate liability_* and aggregate fields. For HEALTH policies, populate medical_payments and aggregate fields.
    - Annual premium heuristics: $650-$2500 auto basic, $2500-$4200 auto premium, $900-$3200 home, $1100-$4800 health; aggregate_limit_per_year MUST be set (basic: 50000-100000, standard: 100000-250000, premium: 300000-500000).
    - Claims counts: claims_count_this_year <= claims_paid_this_year and capped by tier (premium <=3, basic <=1) to echo underwriting discipline.
    - Remaining_aggregate MUST be computed as aggregate_limit_per_year minus (claims_paid_this_year * 15000); never negative, never null.
    - Vehicle metadata for AUTO: vehicle_year between 2012-2025, VIN-style strings (17 chars), commuter usage for 70% of auto policies, commercial for 10%.
    - Garaging addresses: realistic city + ZIP combos for MD/VA/DC/PA, referencing suburbs or corridors used elsewhere in the repo.
    - Customer continuity: ~20% of customers should hold multiple policies; reuse the same garaging address, DOB, and subtle narrative cues so downstream joins stay consistent.
    - Payment recency: keep last_premium_paid_date within 45 days for active/current accounts, 60-120 days for grace/overdue, and explain autopay adoption for low-risk tiers in notes when helpful.
    - Privacy hygiene: use composite names and avoid storing SSNs or other PII beyond what the schema requires; leave sensitive context for downstream claims notes instead of the policy record.
    - Narrative realism: tie higher risk (suspended/cancelled) to overdue payments, multiple claims, or mismatched license info; premium tiers should note telematics/safe-driver incentives.
    - Keep json_schema fidelity 100%; do not emit extra fields or omit required ones. DO NOT leave optional numeric/coverage fields as null unless the policy type doesn't require them (e.g., vehicle fields for home/health).
    """
).strip()

DEFAULT_BATCH_SIZE = 20  # Restored higher batch size for faster throughput; tune if timeouts recur
MAX_BATCH_RETRY_MULTIPLIER = 10  # Larger retry budget to compensate for partial batches


def llm_generate_policies(client: AzureOpenAI, batch_size: int, seed: int, previous_batch: List[PolicyRecord] | None = None) -> List[PolicyRecord]:
    """Call Azure OpenAI structured output to create a batch of policies."""

    user_content = {
        "instruction": "Generate diverse policies across tiers and statuses.",
        "record_count": batch_size,
        "seed": seed,
        "guidance": POLICY_GUIDANCE,
    }
    
    # Add analytics from previous batches to steer diversity
    if previous_batch:
        total = len(previous_batch)
        
        # Calculate actual distributions
        policy_type_dist = {}
        tier_dist = {}
        status_dist = {}
        state_dist = {}
        vehicle_makes = []
        
        for p in previous_batch:
            policy_type_dist[p.policy_type] = policy_type_dist.get(p.policy_type, 0) + 1
            tier_dist[p.tier] = tier_dist.get(p.tier, 0) + 1
            status_dist[p.status] = status_dist.get(p.status, 0) + 1
            state_dist[p.license_state] = state_dist.get(p.license_state, 0) + 1
            if p.vehicle_make:
                vehicle_makes.append(p.vehicle_make)
        
        # Convert to percentages
        analytics = {
            "total_generated": total,
            "policy_type_distribution": {k: f"{(v/total)*100:.1f}%" for k, v in policy_type_dist.items()},
            "tier_distribution": {k: f"{(v/total)*100:.1f}%" for k, v in tier_dist.items()},
            "status_distribution": {k: f"{(v/total)*100:.1f}%" for k, v in status_dist.items()},
            "state_distribution": {k: f"{(v/total)*100:.1f}%" for k, v in state_dist.items()},
            "vehicle_makes_used": list(set(vehicle_makes)),
        }
        
        # Target distributions
        targets = {
            "policy_type_target": {"auto": "60%", "home": "25%", "health": "15%"},
            "tier_target": {"basic": "35%", "standard": "45%", "premium": "20%"},
            "status_target": {"active": "82%", "lapsed": "8%", "suspended": "5%", "cancelled": "5%"},
            "state_target": {"MD": "30%", "VA": "30%", "PA": "25%", "DC": "15%"},
        }
        
        user_content["current_analytics"] = analytics
        user_content["target_distributions"] = targets
        user_content["steering_instruction"] = "Adjust this batch to move closer to target distributions. Prioritize underrepresented categories. Use different vehicle makes than those already used. Vary customer names and addresses."

    messages = [
        {
            "role": "system",
            "content": (
                "You are an insurance data generator producing realistic auto, home, and "
                "health policies for Maryland/Virginia/DC/Pennsylvania customers. "
                "Follow the JSON schema exactly using the provided Pydantic model."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(user_content),
        },
    ]

    response = client.chat.completions.create(
        **build_response_kwargs(
            messages=messages,
            schema=fix_schema_for_azure(PolicyBatch.model_json_schema()),
            seed=seed,
            temperature_default=0.6,
            use_reasoning_override=False,
        )
    )

    payload = extract_response_text(response)
    batch = PolicyBatch.model_validate_json(payload)
    return batch.policies


# ----------------------------------------------------------------------------
# CSV writing helpers
# ----------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "policy_number",
    "customer_id",
    "policy_holder_name",
    "dob",
    "license_number",
    "license_state",
    "policy_type",
    "tier",
    "status",
    "effective_date",
    "expiration_date",
    "annual_premium",
    "payment_status",
    "collision_limit",
    "comprehensive_limit",
    "deductible_collision",
    "deductible_comprehensive",
    "liability_bi_per_person",
    "liability_bi_per_accident",
    "liability_pd",
    "uninsured_motorist",
    "medical_payments",
    "aggregate_limit_per_year",
    "claims_count_this_year",
    "claims_paid_this_year",
    "remaining_aggregate",
    "vehicle_make",
    "vehicle_model",
    "vehicle_year",
    "vehicle_vin",
    "vehicle_usage",
    "garaging_address",
]


def write_csv(records: Iterable[PolicyRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.model_dump())


def print_policy_summary(records: List[PolicyRecord]) -> None:
    if not records:
        print("Policy summary -> no records generated")
        return
    total = len(records)
    type_counts = Counter(record.policy_type for record in records)
    tier_counts = Counter(record.tier for record in records)
    status_counts = Counter(record.status for record in records)
    state_counts = Counter(record.license_state for record in records)
    formatted = {
        "types": ", ".join(f"{k}:{v}" for k, v in type_counts.most_common()),
        "tiers": ", ".join(f"{k}:{v}" for k, v in tier_counts.most_common()),
        "statuses": ", ".join(f"{k}:{v}" for k, v in status_counts.most_common()),
        "states": ", ".join(f"{k}:{v}" for k, v in state_counts.most_common()),
    }
    print(
        "Policy summary -> total: {total}, types [{types}], tiers [{tiers}], statuses [{statuses}], states [{states}]".format(
            total=total,
            types=formatted["types"],
            tiers=formatted["tiers"],
            statuses=formatted["statuses"],
            states=formatted["states"],
        )
    )


# ----------------------------------------------------------------------------
# Main entrypoint
# ----------------------------------------------------------------------------


def generate_dataset(record_count: int, seed: int, batch_size: int = DEFAULT_BATCH_SIZE) -> List[PolicyRecord]:
    load_dotenv()
    print(
        "Policies generator starting -> initializing Azure OpenAI client...",
        flush=True,
    )
    client = build_azure_client()
    print(
        "Policies generator ready -> beginning batch execution",
        flush=True,
    )

    records: List[PolicyRecord] = []
    max_batches = max(1, math.ceil(record_count / batch_size))
    max_attempts = max_batches * MAX_BATCH_RETRY_MULTIPLIER
    attempt = 0

    while len(records) < record_count and attempt < max_attempts:
        attempt += 1
        target = min(batch_size, record_count - len(records))
        previous_batch = records if records else None
        print(
            (
                f"Policies batch {attempt} (aiming for {record_count} total): "
                f"requesting {target} records with {len(records)} collected..."
            ),
            flush=True,
        )
        try:
            policies = llm_generate_policies(client, target, seed + attempt - 1, previous_batch)
        except ValidationError as ex:
            raise RuntimeError(
                f"Azure OpenAI validation failed for batch {attempt}: {ex}"
            ) from ex
        except Exception as ex:
            raise RuntimeError(
                f"Azure OpenAI generation failed for batch {attempt}: {ex}"
            ) from ex
        records.extend(policies)
        print(
            (
                f"Policies batch {attempt} complete -> {len(records)}/{record_count} records"
            ),
            flush=True,
        )

    if len(records) < record_count:
        raise RuntimeError(
            "Policy generation exhausted retry budget before hitting target. "
            f"Generated {len(records)} of {record_count} required records after {attempt} attempts."
        )

    return records[:record_count]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate claims policy portfolio CSV")
    parser.add_argument(
        "--records", type=int, default=1000, help="Number of policies to generate",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Records per Azure OpenAI call (higher == faster, but watch for timeouts)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "policies.csv",
        help="Output CSV path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        records = generate_dataset(args.records, args.seed, args.batch_size)
    except RuntimeError as exc:
        raise SystemExit(f"Azure OpenAI generation failed: {exc}") from exc
    print_policy_summary(records)
    write_csv(records, args.output)
    print(f"Generated {len(records)} policies at {args.output}")


if __name__ == "__main__":
    main()
