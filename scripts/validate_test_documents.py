#!/usr/bin/env python3
"""Validate synthetic test documents stay within placeholder constraints."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable, List

ALLOWED_STATE_ABBR = {"MD", "VA", "DC", "PA"}
US_STATE_ABBR = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}
STATE_TOKEN_PATTERN = re.compile(r",\s*([A-Z]{2})\b")
SHOP_LICENSE_PATTERN = re.compile(r"^MD-SHOP-\d{4}$")
PROVIDER_LICENSE_PATTERN = re.compile(r"^MD-MED-\d{4}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate synthetic document fixtures")
    parser.add_argument(
        "--documents",
        type=Path,
        default=Path("shared/submission/documents"),
        help="Directory that holds synthetic markdown/txt documents",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("shared/submission/document_metadata.json"),
        help="Optional metadata JSON file to validate",
    )
    parser.add_argument(
        "--require-metadata",
        action="store_true",
        help="Fail if the metadata file is missing",
    )
    return parser.parse_args()


def validate_metadata(metadata_path: Path) -> List[str]:
    errors: List[str] = []
    data = json.loads(metadata_path.read_text(encoding="utf-8"))

    policy_number = data.get("policy_number", "")
    if not re.match(r"^[A-Z]+-\d{6}$", policy_number):
        errors.append(f"{metadata_path}: policy_number '{policy_number}' does not match AAAA-###### pattern")

    for doc in data.get("uploaded_documents", []):
        doc_id = doc.get("document_id", "unknown")
        doc_type = doc.get("document_type", "unknown")
        key_data = doc.get("key_data_extracted", {}) or {}

        if doc_type == "repair_estimate":
            license_number = key_data.get("shop_license", "")
            if not SHOP_LICENSE_PATTERN.match(license_number):
                errors.append(
                    f"{metadata_path}::{doc_id}: repair shop license '{license_number}' must match MD-SHOP-####"
                )
        if doc_type == "medical_receipt":
            provider_license = key_data.get("provider_license", "")
            if not PROVIDER_LICENSE_PATTERN.match(provider_license):
                errors.append(
                    f"{metadata_path}::{doc_id}: medical provider license '{provider_license}' must match MD-MED-####"
                )

        location = key_data.get("location") or key_data.get("city")
        if isinstance(location, str):
            states_in_location = {token for token in STATE_TOKEN_PATTERN.findall(location) if token in US_STATE_ABBR}
            disallowed = states_in_location - ALLOWED_STATE_ABBR
            if disallowed:
                errors.append(f"{metadata_path}::{doc_id}: location includes non-Mid-Atlantic states {sorted(disallowed)}")

    return errors


def validate_text_states(document_paths: Iterable[Path]) -> List[str]:
    errors: List[str] = []
    for path in document_paths:
        text = path.read_text(encoding="utf-8")
        found_tokens = {token for token in STATE_TOKEN_PATTERN.findall(text) if token in US_STATE_ABBR}
        disallowed = found_tokens - ALLOWED_STATE_ABBR
        if disallowed:
            errors.append(f"{path}: contains disallowed state abbreviations {sorted(disallowed)}")
    return errors


def main() -> None:
    args = parse_args()
    if not args.documents.exists():
        raise SystemExit(f"Document directory not found: {args.documents}")
    metadata_path: Path | None = args.metadata
    if metadata_path is not None and not metadata_path.exists():
        if args.require_metadata:
            raise SystemExit(f"Metadata file not found: {metadata_path}")
        print(f"Metadata file not found, skipping metadata validation: {metadata_path}")
        metadata_path = None

    markdown_files = sorted(p for p in args.documents.iterdir() if p.suffix.lower() in {".md", ".txt"})
    errors = []
    if metadata_path is not None:
        errors.extend(validate_metadata(metadata_path))
    errors.extend(validate_text_states(markdown_files))

    if errors:
        print("Synthetic document validation failed:")
        for err in errors:
            print(f"- {err}")
        raise SystemExit(1)

    print("Synthetic document validation passed.")


if __name__ == "__main__":
    main()
