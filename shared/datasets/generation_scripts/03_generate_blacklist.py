#!/usr/bin/env python3
"""Generate blacklist.csv with vendor references using Azure OpenAI."""

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

Severity = Literal["low", "medium", "high", "critical"]
Status = Literal["active", "under_investigation", "resolved"]
EntityType = Literal["customer", "repair_shop", "medical_provider", "attorney"]


class BlacklistRecord(BaseModel):
    entity_id: str = Field(..., pattern=r"^BL-\d{3}$")
    entity_type: EntityType
    business_name: Optional[str]
    tax_id: str
    license_number: Optional[str]
    reason: str
    date_flagged: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    severity: Severity
    status: Status
    last_verified: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str


class BlacklistBatch(BaseModel):
    entries: List[BlacklistRecord]


BLACKLIST_GUIDANCE = dedent(
    """
    Enforcement goals:
    - Entity types: ~35% customers, 30% repair_shop, 25% medical_provider, 10% attorneys. Tie records to vendor_sample when available.
    - Severity mix: low 10%, medium 40%, high 35%, critical 15. Higher severity should include corroborating details in notes.
    - Status mix: active 70%, under_investigation 20%, resolved 10; resolved rows should include last_verified within last 120 days.
    - Reasons should cite concrete fraud indicators (duplicate VIN usage, excessive billing variance, staged accidents, licensing gaps). Reference vendor license numbers when applicable.
    - Tax IDs: use EIN-like formats (##-#######) for businesses or masked SSNs for customers.
    - Dates: date_flagged and last_verified within past 24 months; critical cases should have last_verified within 60 days.
    - Evidence references: cite investigation IDs, claim numbers, or external reports in notes ("Ref: SIU-2025-14") and favor "alleged" language unless fraud is fully adjudicated.
    - Notes: 1-2 sentences summarizing investigation findings and recommended next action (suspend payments, require second adjuster, etc.) while maintaining professional, non-accusatory tone.
    - Expiration discipline: remind reviewers to sunset entries if last_verified exceeds 365 days; resolved cases should highlight remediation ("payments reinstated after documentation review").
    - Keep json_schema fidelity; never invent new columns.
    """
).strip()

DEFAULT_BATCH_SIZE = 25  # Restored higher batch size; adjust downward if API calls timeout
MAX_BATCH_RETRY_MULTIPLIER = 8  # Provide generous retries for structured outputs


def llm_generate(client: AzureOpenAI, count: int, seed: int, vendor_sample: List[dict], previous_batch: List[BlacklistRecord] | None = None) -> List[BlacklistRecord]:
    user_content = {
        "record_count": count,
        "seed": seed,
        "vendor_examples": vendor_sample,
        "rules": {
            "severity_mix": {"low": 0.1, "medium": 0.4, "high": 0.35, "critical": 0.15},
            "statuses": {"active": 0.8, "under_investigation": 0.15, "resolved": 0.05},
        },
        "guidance": BLACKLIST_GUIDANCE,
    }
    
    if previous_batch:
        total = len(previous_batch)
        
        # Calculate distributions
        entity_type_dist = {}
        severity_dist = {}
        status_dist = {}
        reason_keywords = []
        
        for e in previous_batch:
            entity_type_dist[e.entity_type] = entity_type_dist.get(e.entity_type, 0) + 1
            severity_dist[e.severity] = severity_dist.get(e.severity, 0) + 1
            status_dist[e.status] = status_dist.get(e.status, 0) + 1
            # Extract key fraud patterns
            if "fraud" in e.reason.lower():
                reason_keywords.append(e.reason.split()[0:3])
        
        analytics = {
            "total_generated": total,
            "entity_type_distribution": {k: f"{(v/total)*100:.1f}%" for k, v in entity_type_dist.items()},
            "severity_distribution": {k: f"{(v/total)*100:.1f}%" for k, v in severity_dist.items()},
            "status_distribution": {k: f"{(v/total)*100:.1f}%" for k, v in status_dist.items()},
        }
        
        targets = {
            "severity_target": {"low": "10%", "medium": "40%", "high": "35%", "critical": "15%"},
            "status_target": {"active": "80%", "under_investigation": "15%", "resolved": "5%"},
        }
        
        user_content["current_analytics"] = analytics
        user_content["target_distributions"] = targets
        user_content["steering_instruction"] = "Balance severity and status to match targets. Create varied fraud scenarios (billing fraud, identity theft, staged accidents, phantom providers, etc.). Use diverse business names and tax IDs."
    
    messages = [
        {
            "role": "system",
            "content": "Generate flagged entities for an insurance SIU team using the JSON schema.",
        },
        {
            "role": "user",
            "content": json.dumps(user_content),
        },
    ]
    response = client.chat.completions.create(
        **build_response_kwargs(
            messages=messages,
            schema=fix_schema_for_azure(BlacklistBatch.model_json_schema()),
            seed=seed,
            temperature_default=0.6,
        )
    )
    payload = extract_response_text(response)
    return BlacklistBatch.model_validate_json(payload).entries


def generate_dataset(
    client: AzureOpenAI,
    total_records: int,
    seed: int,
    vendor_sample: List[dict],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> List[BlacklistRecord]:
    records: List[BlacklistRecord] = []
    max_batches = max(1, math.ceil(total_records / batch_size))
    max_attempts = max_batches * MAX_BATCH_RETRY_MULTIPLIER
    attempt = 0

    while len(records) < total_records and attempt < max_attempts:
        attempt += 1
        target = min(batch_size, total_records - len(records))
        previous_batch = records if records else None
        print(
            (
                f"Blacklist batch {attempt} (aiming for {total_records} total): "
                f"requesting {target} records with {len(records)} collected..."
            ),
            flush=True,
        )
        try:
            entries = llm_generate(client, target, seed + attempt - 1, vendor_sample, previous_batch)
        except ValidationError as ex:
            raise RuntimeError(f"Azure OpenAI blacklist validation failed on batch {attempt}: {ex}") from ex
        except Exception as ex:  # pragma: no cover
            raise RuntimeError(f"Azure OpenAI blacklist generation failed on batch {attempt}: {ex}") from ex
        records.extend(entries)
        print(
            (
                f"Blacklist batch {attempt} complete -> {len(records)}/{total_records} records"
            ),
            flush=True,
        )

    if len(records) < total_records:
        raise RuntimeError(
            "Blacklist generation exhausted retry budget before hitting target. "
            f"Generated {len(records)} of {total_records} required records after {attempt} attempts."
        )

    return records[:total_records]


OUTPUT_COLUMNS = [
    "entity_id",
    "entity_type",
    "business_name",
    "tax_id",
    "license_number",
    "reason",
    "date_flagged",
    "severity",
    "status",
    "last_verified",
    "notes",
]


def write_csv(records: Iterable[BlacklistRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.model_dump())


def print_blacklist_summary(records: List[BlacklistRecord]) -> None:
    if not records:
        print("Blacklist summary -> no records generated")
        return
    total = len(records)
    entity_counts = Counter(entry.entity_type for entry in records)
    severity_counts = Counter(entry.severity for entry in records)
    status_counts = Counter(entry.status for entry in records)
    print(
        "Blacklist summary -> total: {total}, entity_types [{entities}], severity [{severity}], status [{status}]".format(
            total=total,
            entities=", ".join(f"{k}:{v}" for k, v in entity_counts.most_common()),
            severity=", ".join(f"{k}:{v}" for k, v in severity_counts.most_common()),
            status=", ".join(f"{k}:{v}" for k, v in status_counts.most_common()),
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate blacklist.csv")
    parser.add_argument("--records", type=int, default=50)
    parser.add_argument("--seed", type=int, default=321)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Records per Azure OpenAI call",
    )
    parser.add_argument(
        "--vendors",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "vendors.csv",
        help="Optional vendors CSV to reference",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "risk" / "blacklist.csv",
    )
    return parser.parse_args()


def load_vendor_sample(path: Path, sample_size: int = 10) -> List[dict]:
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return df.sample(min(sample_size, len(df))).to_dict(orient="records")


def main() -> None:
    load_dotenv()
    args = parse_args()
    vendor_sample = load_vendor_sample(args.vendors)

    try:
        print("Blacklist generator starting -> initializing Azure OpenAI client...", flush=True)
        client = build_azure_client()
        print("Blacklist generator ready -> beginning batch execution", flush=True)
        records = generate_dataset(client, args.records, args.seed, vendor_sample, args.batch_size)
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"Azure OpenAI generation failed: {exc}") from exc

    print_blacklist_summary(records)
    write_csv(records, args.output)
    print(f"Generated {len(records)} blacklist entries at {args.output}")


if __name__ == "__main__":
    main()
