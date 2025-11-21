#!/usr/bin/env python3
"""Generate vendors.csv for the claims orchestration lab using Azure OpenAI."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from textwrap import dedent
from typing import Iterable, List, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from azure_llm import (
    AzureOpenAI,
    build_azure_client,
    build_response_kwargs,
    extract_response_text,
    fix_schema_for_azure,
)

VendorType = Literal["repair_shop", "medical_provider"]
AuditStatus = Literal["passed", "conditional", "failed"]


class VendorRecord(BaseModel):
    vendor_id: str = Field(..., pattern=r"^VND-\d{3}$")
    vendor_type: VendorType
    business_name: str
    license_number: str
    license_state: Literal["MD", "VA", "DC", "PA"]
    license_expiry: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    rating: float = Field(..., ge=3.0, le=5.0)
    total_claims_processed: int = Field(..., ge=10, le=5000)
    avg_estimate_accuracy: float = Field(..., ge=0.8, le=1.0)
    contact_phone: str
    address: str
    city: str
    state: str
    zip: str
    last_audit_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    audit_status: AuditStatus
    notes: str


class VendorBatch(BaseModel):
    vendors: List[VendorRecord]


VENDOR_GUIDANCE = dedent(
    """
    Vendor mix & coverage:
    - Maintain ~55% repair_shop, 45% medical_provider split; keep both types represented in every batch.
    - License formats: repair shops use MD-SHOP-#### style values; medical providers use MD-MED-#### or NPIs.
    - Multi-state coverage: operate across MD/VA/DC/PA. license_state must align with address state but vendors may serve nearby states (note that in notes field).
    - Rating logic: 3.2-3.6 for probationary vendors, 4.0-4.5 for most, ≥4.8 only for elite partners. ratings should correlate with audit_status notes.
    - Audit status mix: passed 70%, conditional 20%, failed 10%. Failed vendors should have recent last_audit_date and cautionary notes.
    - Volume realism: total_claims_processed 50-5000 depending on vendor_type; avg_estimate_accuracy 0.82-0.98 with higher accuracy for medical specialists.
    - Contact info: Use realistic NANP phone numbers, addresses referencing known corridors (Baltimore, Richmond, Pittsburgh, DC suburbs, etc.).
    - Privacy hygiene: use composite business names and never leak PII (no personal cell numbers, emails, or specific patient names); keep notes focused on business operations.
    - Specialty diversity: rotate subspecialties (EV-certified collision, glass repair, telehealth triage, orthopedic rehab) so adjusters can match vendors to scenario types.
    - Notes column: include 1-2 concise sentences highlighting specialties, coverage radius, or recent audit findings; mention OEM certifications, telehealth support, or fraud monitoring when relevant.
    - Audit follow-up: conditional/failed statuses must include remediation plans ("documentation refresh scheduled in 45 days", "pairing with mentor shop") to emphasize partnership tone.
    - Ensure vendor_id uniqueness (VND-000 series) and deterministic formatting.
    - Keep json_schema fidelity and avoid extra keys.
    """
).strip()

DEFAULT_BATCH_SIZE = 25  # Higher batch size for faster vendor generation; lower if Azure timeouts return
MAX_BATCH_RETRY_MULTIPLIER = 8  # Allow multiple retries when batches return invalid rows


def llm_generate_vendors(client: AzureOpenAI, count: int, seed: int, previous_batch: List[VendorRecord] | None = None) -> List[VendorRecord]:
    user_content = {
        "record_count": count,
        "seed": seed,
        "requirements": {
            "states": ["MD", "VA", "DC", "PA"],
            "license_formats": ["MD-SHOP-####", "MD-MED-####"],
        },
        "guidance": VENDOR_GUIDANCE,
    }
    
    if previous_batch:
        total = len(previous_batch)

        vendor_type_dist: dict[str, int] = {}
        audit_status_dist: dict[str, int] = {}
        state_dist: dict[str, int] = {}
        license_state_dist: dict[str, int] = {}
        rating_buckets = {"3-3.6": 0, "3.6-4.4": 0, "4.4-5": 0}

        for vendor in previous_batch:
            vendor_type_dist[vendor.vendor_type] = vendor_type_dist.get(vendor.vendor_type, 0) + 1
            audit_status_dist[vendor.audit_status] = audit_status_dist.get(vendor.audit_status, 0) + 1
            state_dist[vendor.state] = state_dist.get(vendor.state, 0) + 1
            license_state_dist[vendor.license_state] = license_state_dist.get(vendor.license_state, 0) + 1

            if vendor.rating < 3.6:
                rating_buckets["3-3.6"] += 1
            elif vendor.rating < 4.4:
                rating_buckets["3.6-4.4"] += 1
            else:
                rating_buckets["4.4-5"] += 1

        def _fmt(dist: dict[str, int]) -> dict[str, str]:
            return {k: f"{(v/total)*100:.1f}%" for k, v in dist.items()}

        analytics = {
            "total_generated": total,
            "vendor_type_distribution": _fmt(vendor_type_dist),
            "audit_status_distribution": _fmt(audit_status_dist),
            "state_distribution": _fmt(state_dist),
            "license_state_distribution": _fmt(license_state_dist),
            "rating_distribution": _fmt(rating_buckets),
        }

        targets = {
            "vendor_type_target": {"repair_shop": "55%", "medical_provider": "45%"},
            "audit_status_target": {"passed": "70%", "conditional": "20%", "failed": "10%"},
            "state_target": {"MD": "30%", "VA": "30%", "PA": "25%", "DC": "15%"},
            "rating_target": {"3-3.6": "20%", "3.6-4.4": "55%", "4.4-5": "25%"},
        }

        user_content["current_analytics"] = analytics
        user_content["target_distributions"] = targets
        user_content["steering_instruction"] = (
            "Favor underrepresented vendor types/states, adjust audit mix toward targets, and vary ratings"
            " to better match the requested distribution."
        )
    
    messages = [
        {
            "role": "system",
            "content": "Create realistic repair shop and medical provider records for claims processing.",
        },
        {
            "role": "user",
            "content": json.dumps(user_content),
        },
    ]

    response = client.chat.completions.create(
        **build_response_kwargs(
            messages=messages,
            schema=fix_schema_for_azure(VendorBatch.model_json_schema()),
            seed=seed,
            temperature_default=0.6,
        )
    )
    payload = extract_response_text(response)
    return VendorBatch.model_validate_json(payload).vendors


def generate_dataset(client: AzureOpenAI, total_records: int, seed: int, batch_size: int = DEFAULT_BATCH_SIZE) -> List[VendorRecord]:
    records: List[VendorRecord] = []
    max_batches = max(1, math.ceil(total_records / batch_size))
    max_attempts = max_batches * MAX_BATCH_RETRY_MULTIPLIER
    attempt = 0

    while len(records) < total_records and attempt < max_attempts:
        attempt += 1
        target = min(batch_size, total_records - len(records))
        previous_batch = records if records else None
        print(
            (
                f"Vendors batch {attempt} (aiming for {total_records} total): "
                f"requesting {target} records with {len(records)} collected..."
            ),
            flush=True,
        )
        try:
            vendors = llm_generate_vendors(client, target, seed + attempt - 1, previous_batch)
        except ValidationError as ex:
            raise RuntimeError(f"Azure OpenAI vendor validation failed on batch {attempt}: {ex}") from ex
        except Exception as ex:  # pragma: no cover
            raise RuntimeError(f"Azure OpenAI vendor generation failed on batch {attempt}: {ex}") from ex
        records.extend(vendors)
        print(
            (
                f"Vendors batch {attempt} complete -> {len(records)}/{total_records} records"
            ),
            flush=True,
        )

    if len(records) < total_records:
        raise RuntimeError(
            "Vendor generation exhausted retry budget before hitting target. "
            f"Generated {len(records)} of {total_records} required records after {attempt} attempts."
        )

    return records[:total_records]


OUTPUT_COLUMNS = [
    "vendor_id",
    "vendor_type",
    "business_name",
    "license_number",
    "license_state",
    "license_expiry",
    "rating",
    "total_claims_processed",
    "avg_estimate_accuracy",
    "contact_phone",
    "address",
    "city",
    "state",
    "zip",
    "last_audit_date",
    "audit_status",
    "notes",
]


def write_csv(records: Iterable[VendorRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.model_dump())


def print_vendor_summary(records: List[VendorRecord]) -> None:
    if not records:
        print("Vendor summary -> no records generated")
        return
    total = len(records)
    type_counts = Counter(record.vendor_type for record in records)
    status_counts = Counter(record.audit_status for record in records)
    state_counts = Counter(record.state for record in records)
    print(
        "Vendor summary -> total: {total}, types [{types}], audit_status [{status}], states [{states}]".format(
            total=total,
            types=", ".join(f"{k}:{v}" for k, v in type_counts.most_common()),
            status=", ".join(f"{k}:{v}" for k, v in status_counts.most_common()),
            states=", ".join(f"{k}:{v}" for k, v in state_counts.most_common()),
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate vendors.csv")
    parser.add_argument("--records", type=int, default=100)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Records per Azure OpenAI call",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "vendors.csv",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    try:
        print("Vendors generator starting -> initializing Azure OpenAI client...", flush=True)
        client = build_azure_client()
        print("Vendors generator ready -> beginning batch execution", flush=True)
        records = generate_dataset(client, args.records, args.seed, args.batch_size)
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"Azure OpenAI generation failed: {exc}") from exc

    print_vendor_summary(records)
    write_csv(records, args.output)
    print(f"Generated {len(records)} vendors at {args.output}")


if __name__ == "__main__":
    main()
