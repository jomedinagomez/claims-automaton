"""Utilities for normalizing incoming claim submissions."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def parse_freeform_claim(content: str, source_path: Optional[Path] = None) -> Dict[str, Any]:
    """Convert markdown or email-style submissions into a structured payload."""
    sanitized = content.strip()
    if not sanitized:
        raise ValueError("Claim submission is empty")

    policy_match = re.search(r"policy\s+number\s+is\s+([A-Z0-9-]+)", sanitized, re.IGNORECASE)
    policy_number = policy_match.group(1) if policy_match else "UNKNOWN"

    date_patterns = [
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?)",
        r"(\d{1,2}/\d{1,2}/\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
    ]
    incident_date: Optional[str] = None
    for pattern in date_patterns:
        match = re.search(pattern, sanitized, re.IGNORECASE)
        if match:
            incident_date = match.group(0)
            break

    email_match = re.search(r"From:\s*([^\n]+)", sanitized)
    subject_match = re.search(r"Subject:\s*([^\n]+)", sanitized)

    customer_email = email_match.group(1).strip() if email_match else "unknown@example.com"
    customer_name = customer_email.split("@")[0].replace(".", " ").title()

    phone_match = re.search(r"(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})", sanitized)
    customer_phone = phone_match.group(1) if phone_match else "555-000-0000"

    documents = re.findall(r"-\s+([a-zA-Z0-9_.-]+\.(?:md|txt|pdf|jpg|png))", sanitized)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    claim_id = f"CLM-{timestamp[-10:]}"

    payload: Dict[str, Any] = {
        "claim_id": claim_id,
        "policy_number": policy_number,
        "customer": {
            "name": customer_name,
            "email": customer_email,
            "phone": customer_phone,
        },
        "incident": {
            "date": incident_date or "unknown",
            "description": sanitized,
            "location": "I-95 North" if "I-95" in sanitized else "unknown",
        },
        "documents": documents,
        "submission_method": "email",
        "original_content": sanitized,
    }

    if subject_match:
        payload.setdefault("metadata", {})["subject"] = subject_match.group(1).strip()

    if source_path:
        payload["source_file"] = str(Path(source_path))

    return payload
