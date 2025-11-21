"""Semantic Kernel native tool plugins backed by shared datasets."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import re
from statistics import mean
from typing import Any, Dict, List, Optional

try:  # Semantic Kernel renamed the decorator in past releases; keep compatibility.
    from semantic_kernel.functions.kernel_function_decorator import kernel_function
except ImportError:  # pragma: no cover - fallback for older SK builds
    from semantic_kernel.functions.kernel_function import kernel_function

from .repository import SharedDataRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _parse_date(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.debug("Unable to parse date: %s", value)
        return None


def _ensure_dict(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    import json

    try:
        return json.loads(payload)
    except Exception as exc:  # pragma: no cover - defensive branch
        raise ValueError("Expected JSON object for payload") from exc


# ---------------------------------------------------------------------------
# Policy + coverage tools
# ---------------------------------------------------------------------------


class PolicyTools:
    """Policy lookups and coverage calculators."""

    def __init__(self, repo: SharedDataRepository) -> None:
        self.repo = repo
        self._policies = self.repo.load_dataframe("policies.csv")
        self._coverage = self.repo.load_dataframe("coverage_matrix.csv")

    @kernel_function(name="lookup_policy_details", description="Return policy metadata for a policy number")
    async def lookup_policy_details(self, policy_number: str) -> dict[str, Any]:
        match = self._policies[self._policies["policy_number"] == policy_number]
        if match.empty:
            return {"found": False, "policy_number": policy_number}
        record = SharedDataRepository.coerce_record(match.iloc[0].to_dict())
        return {"found": True, "policy": record}

    @kernel_function(
        name="validate_policy_status",
        description="Validate that the policy is active for the given incident date",
    )
    async def validate_policy_status(self, policy_number: str, incident_date: str | None = None) -> dict[str, Any]:
        match = self._policies[self._policies["policy_number"] == policy_number]
        if match.empty:
            return {
                "policy_number": policy_number,
                "active": False,
                "reason": "policy_not_found",
            }
        row = SharedDataRepository.coerce_record(match.iloc[0].to_dict())
        effective = _parse_date(row.get("effective_date"))
        expiration = _parse_date(row.get("expiration_date"))
        incident = _parse_date(incident_date) or datetime.utcnow()
        active_window = effective and expiration and effective <= incident <= expiration
        return {
            "policy_number": policy_number,
            "status": row.get("status"),
            "active": bool(active_window),
            "effective_date": row.get("effective_date"),
            "expiration_date": row.get("expiration_date"),
            "policy_type": row.get("policy_type"),
            "tier": row.get("tier"),
        }

    @kernel_function(
        name="check_coverage_matrix",
        description="Return deductible, limits, and exclusions for a policy tier and claim type",
    )
    async def check_coverage_matrix(self, policy_tier: str, claim_type: str) -> dict[str, Any]:
        subset = self._coverage[
            (self._coverage["policy_tier"].str.lower() == policy_tier.lower())
            & (self._coverage["claim_type"].str.lower() == claim_type.lower())
        ]
        if subset.empty:
            return {
                "policy_tier": policy_tier,
                "claim_type": claim_type,
                "found": False,
            }
        row = SharedDataRepository.coerce_record(subset.iloc[0].to_dict())
        return {
            "policy_tier": policy_tier,
            "claim_type": claim_type,
            "found": True,
            "coverage": row,
        }


# ---------------------------------------------------------------------------
# Claims history + frequency
# ---------------------------------------------------------------------------


class ClaimsHistoryTools:
    """Historical claim lookups and derived metrics."""

    def __init__(self, repo: SharedDataRepository) -> None:
        self.repo = repo
        self._history = self.repo.load_dataframe("historical/claims_history.csv")

    @kernel_function(name="lookup_claims_history", description="Fetch prior claims for a customer")
    async def lookup_claims_history(self, customer_id: str, policy_number: str | None = None) -> dict[str, Any]:
        records = self._history[self._history["customer_id"] == customer_id]
        if policy_number:
            records = records[records["policy_number"] == policy_number]
        entries = [SharedDataRepository.coerce_record(row) for row in records.to_dict(orient="records")]
        return {
            "customer_id": customer_id,
            "policy_number": policy_number,
            "claim_count": len(entries),
            "claims": entries,
        }

    @kernel_function(
        name="calculate_frequency_metrics",
        description="Calculate claim frequency stats over a rolling window",
    )
    async def calculate_frequency_metrics(self, customer_id: str, lookback_months: int = 24) -> dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=30 * lookback_months)
        subset = self._history[self._history["customer_id"] == customer_id]
        recent: List[dict[str, Any]] = []
        for record in subset.to_dict(orient="records"):
            incident = _parse_date(record.get("incident_date"))
            if not incident or incident < cutoff:
                continue
            recent.append(record)
        durations = [int(record.get("processing_days", 0) or 0) for record in recent]
        avg_duration = mean(durations) if durations else 0
        return {
            "customer_id": customer_id,
            "lookback_months": lookback_months,
            "recent_claims": len(recent),
            "average_processing_days": avg_duration,
        }


# ---------------------------------------------------------------------------
# Fraud + risk tools
# ---------------------------------------------------------------------------


class FraudTools:
    """Fraud heuristics backed by blacklist + historical data."""

    def __init__(self, repo: SharedDataRepository) -> None:
        self.repo = repo
        self._blacklist = self.repo.load_dataframe("risk/blacklist.csv")
        self._history_tools = ClaimsHistoryTools(repo)

    @kernel_function(name="check_blacklist", description="Check entities against the internal blacklist")
    async def check_blacklist(
        self,
        entity_id: str | None = None,
        tax_id: str | None = None,
        license_number: str | None = None,
    ) -> dict[str, Any]:
        subset = self._blacklist
        if entity_id:
            subset = subset[subset["entity_id"].str.lower() == entity_id.lower()]
        if tax_id and not subset.empty:
            subset = subset[subset["tax_id"].str.lower() == tax_id.lower()]
        if license_number and not subset.empty:
            subset = subset[subset["license_number"].str.lower() == license_number.lower()]
        matches = [SharedDataRepository.coerce_record(row) for row in subset.to_dict(orient="records")]
        return {
            "match_count": len(matches),
            "matches": matches,
        }

    @kernel_function(
        name="detect_duplicate_claims",
        description="Identify claims filed close together for the same policy",
    )
    async def detect_duplicate_claims(self, policy_number: str, incident_date: str, window_days: int = 30) -> dict[str, Any]:
        history = self._history_tools._history
        incident_dt = _parse_date(incident_date)
        if incident_dt is None:
            return {
                "policy_number": policy_number,
                "incident_date": incident_date,
                "duplicates": [],
                "duplicate_count": 0,
            }
        subset = history[history["policy_number"] == policy_number]
        duplicates: List[dict[str, Any]] = []
        for record in subset.to_dict(orient="records"):
            past_dt = _parse_date(record.get("incident_date"))
            if not past_dt:
                continue
            if abs((incident_dt - past_dt).days) <= window_days:
                duplicates.append(record)
        return {
            "policy_number": policy_number,
            "incident_date": incident_date,
            "window_days": window_days,
            "duplicate_count": len(duplicates),
            "duplicates": [SharedDataRepository.coerce_record(row) for row in duplicates],
        }


# ---------------------------------------------------------------------------
# External evidence
# ---------------------------------------------------------------------------


class ExternalSignalsTools:
    """Adapters for public data like police reports and weather."""

    def __init__(self, repo: SharedDataRepository) -> None:
        self.repo = repo
        self._police_reports = self.repo.load_json("external/police_reports.json").get("reports", [])
        self._weather_events = self.repo.load_json("external/weather_events.json").get("events", [])

    @kernel_function(name="verify_police_report", description="Verify that a police report exists and is validated")
    async def verify_police_report(self, report_number: str) -> dict[str, Any]:
        match = next(
            (report for report in self._police_reports if report.get("report_number") == report_number),
            None,
        )
        if not match:
            return {"report_number": report_number, "found": False}
        return {"report_number": report_number, "found": True, "report": match}

    @kernel_function(
        name="check_weather_events",
        description="Check severe weather events for a date/location",
    )
    async def check_weather_events(self, date: str, location: str) -> dict[str, Any]:
        location_lower = location.lower()
        events = [
            event
            for event in self._weather_events
            if event.get("date") == date and location_lower in event.get("location", "").lower()
        ]
        return {
            "date": date,
            "location": location,
            "events": events,
            "event_count": len(events),
        }


# ---------------------------------------------------------------------------
# Vendor + medical tools
# ---------------------------------------------------------------------------


class VendorTools:
    """Vendor credential and pricing helpers."""

    def __init__(self, repo: SharedDataRepository) -> None:
        self.repo = repo
        self._vendors = self.repo.load_dataframe("vendors.csv")

    @kernel_function(name="verify_vendor_credentials", description="Validate repair or medical vendor credentials")
    async def verify_vendor_credentials(
        self,
        vendor_id: str | None = None,
        license_number: str | None = None,
    ) -> dict[str, Any]:
        records = self._vendors
        if vendor_id:
            records = records[records["vendor_id"].str.lower() == vendor_id.lower()]
        if license_number and not records.empty:
            records = records[records["license_number"].str.lower() == license_number.lower()]
        if records.empty:
            return {"found": False, "vendor_id": vendor_id, "license_number": license_number}
        row = SharedDataRepository.coerce_record(records.iloc[0].to_dict())
        return {"found": True, "vendor": row}

    @kernel_function(
        name="validate_vendor_pricing",
        description="Compare vendor estimate against historical accuracy benchmarks. If estimate_amount is not provided, returns vendor accuracy info only.",
    )
    async def validate_vendor_pricing(self, vendor_id: str, estimate_amount: float = 0.0) -> dict[str, Any]:
        record = self._vendors[self._vendors["vendor_id"].str.lower() == vendor_id.lower()]
        if record.empty:
            return {"found": False, "vendor_id": vendor_id}
        row = SharedDataRepository.coerce_record(record.iloc[0].to_dict())
        avg_accuracy = float(row.get("avg_estimate_accuracy", 1.0) or 1.0)
        variance_pct = abs(1 - avg_accuracy) * 100
        
        # Only flag pricing if estimate_amount was actually provided
        pricing_flag = False
        if estimate_amount > 0:
            pricing_flag = variance_pct > 12 or estimate_amount > 25000
        
        return {
            "vendor_id": vendor_id,
            "found": True,
            "estimate_amount": estimate_amount if estimate_amount > 0 else None,
            "avg_estimate_accuracy": avg_accuracy,
            "variance_percent": round(variance_pct, 2),
            "pricing_flagged": pricing_flag,
        }


class MedicalTools:
    """Medical code validation + credential checks."""

    def __init__(self, repo: SharedDataRepository, vendor_tools: VendorTools) -> None:
        self.repo = repo
        self.vendor_tools = vendor_tools
        self._codes = self.repo.load_dataframe("external/medical_codes.csv")

    @kernel_function(name="validate_medical_codes", description="Validate ICD-10 / CPT codes against reference data")
    async def validate_medical_codes(self, code: str) -> dict[str, Any]:
        match = self._codes[self._codes["icd10_code"].str.lower() == code.lower()]
        if match.empty:
            return {"code": code, "valid": False}
        row = SharedDataRepository.coerce_record(match.iloc[0].to_dict())
        return {"code": code, "valid": True, "details": row}

    @kernel_function(
        name="verify_provider_credentials",
        description="Verify medical provider credentials via vendor registry",
    )
    async def verify_provider_credentials(self, license_number: str) -> dict[str, Any]:
        result = await self.vendor_tools.verify_vendor_credentials(license_number=license_number)
        if not result.get("found"):
            return {"license_number": license_number, "found": False}
        vendor = result["vendor"]
        if vendor.get("vendor_type") != "medical_provider":
            vendor["warning"] = "License belongs to non-medical vendor"
        return {"license_number": license_number, "found": True, "vendor": vendor}


# ---------------------------------------------------------------------------
# Document tooling
# ---------------------------------------------------------------------------


class DocumentTools:
    """Document completeness + authenticity helpers."""

    def __init__(self, repo: SharedDataRepository) -> None:
        self.repo = repo

    @kernel_function(name="check_document_completeness", description="Compare provided docs vs. requirements")
    async def check_document_completeness(
        self,
        required_documents: List[str],
        provided_documents: List[str],
    ) -> dict[str, Any]:
        required = [doc.strip().lower() for doc in required_documents]
        provided = [doc.strip().lower() for doc in provided_documents]
        missing = [doc for doc in required if doc not in provided]
        return {
            "required_count": len(required_documents),
            "provided_count": len(provided_documents),
            "missing_documents": missing,
            "complete": len(missing) == 0,
        }

    @kernel_function(
        name="check_information_completeness", 
        description="Check if all required claim information has been provided by the customer"
    )
    async def check_information_completeness(
        self,
        claim_type: str,
        claim_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Check what information is missing from the claim based on required_information.yaml.
        Returns missing_information list with conversational prompts to ask the user.
        """
        import yaml
        from pathlib import Path
        
        # Load required information config
        config_path = Path(__file__).parent.parent.parent.parent.parent / "shared" / "config" / "required_information.yaml"
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning(f"Required information config not found at {config_path}")
            return {"missing_information": [], "complete": True}
        
        missing_info = []
        
        # Check core information (always required)
        core_required = config.get("core_information", {}).get("always_required", {})
        for field_name, field_config in core_required.items():
            # Check if this field exists and has a value in claim_context
            value = claim_context.get(field_name)
            if not value or (isinstance(value, str) and not value.strip()):
                missing_info.append({
                    "field": field_name,
                    "question": field_config.get("how_to_ask", f"What is the {field_name}?"),
                    "description": field_config.get("description", ""),
                    "example": field_config.get("example", "")
                })
        
        # Check claim type specific information
        claim_type_config = config.get("claim_type_specific", {}).get(claim_type, {})
        required_data = claim_type_config.get("required_data", {})
        
        for field_name, field_config in required_data.items():
            # Skip conditional fields if condition not met
            conditional = field_config.get("conditional")
            if conditional:
                # Simple condition parsing (e.g., "injuries_occurred == yes")
                if "==" in conditional:
                    condition_field, condition_value = conditional.split("==")
                    condition_field = condition_field.strip()
                    condition_value = condition_value.strip().strip('"\'')
                    actual_value = str(claim_context.get(condition_field, "")).lower()
                    if actual_value != condition_value.lower():
                        continue  # Skip this field, condition not met
            
            # Check if field is provided
            value = claim_context.get(field_name)
            if not value or (isinstance(value, str) and not value.strip()):
                missing_info.append({
                    "field": field_name,
                    "question": field_config.get("how_to_ask", f"What is the {field_name}?"),
                    "description": field_config.get("description", ""),
                    "example": field_config.get("example", ""),
                    "conditional": conditional or None
                })
        
        return {
            "missing_information": missing_info,
            "complete": len(missing_info) == 0,
            "claim_type": claim_type
        }

    @kernel_function(name="extract_document_metadata", description="Extract lightweight metadata from a document")
    async def extract_document_metadata(self, document_name: str) -> dict[str, Any]:
        try:
            contents = self.repo.load_submission_document(document_name)
        except FileNotFoundError as exc:
            return {
                "document": document_name,
                "missing": True,
                "error": str(exc),
            }
        lines = contents.splitlines()
        currency_matches = re.findall(r"\$\d+[\d,.]*", contents)
        return {
            "document": document_name,
            "line_count": len(lines),
            "character_count": len(contents),
            "currency_mentions": currency_matches,
            "contains_signature": "signature" in contents.lower(),
        }

    @kernel_function(
        name="validate_document_authenticity",
        description="Simple authenticity heuristics based on structure + key fields",
    )
    async def validate_document_authenticity(self, document_name: str) -> dict[str, Any]:
        try:
            contents = self.repo.load_submission_document(document_name)
        except FileNotFoundError as exc:
            return {
                "document": document_name,
                "missing": True,
                "authenticity_score": 0,
                "notes": str(exc),
            }
        score = 50
        if "license:" in contents.lower():
            score += 15
        if "estimate number" in contents.lower() or "report" in contents.lower():
            score += 15
        if "signature" in contents.lower():
            score += 10
        if "__" in contents:  # missing signature lines reduce score
            score -= 5
        score = max(0, min(100, score))
        return {
            "document": document_name,
            "authenticity_score": score,
            "notes": "Heuristic evaluation only",
        }


# ---------------------------------------------------------------------------
# Handoff + decision helpers
# ---------------------------------------------------------------------------


class HandoffTools:
    """Helpers for capturing human decisions and packaging payloads."""

    def __init__(self, repo: SharedDataRepository) -> None:
        self.repo = repo
        self._schema = self.repo.load_config("handoff_schema.json")

    @kernel_function(name="capture_human_decision", description="Structure human approve/deny decisions")
    async def capture_human_decision(
        self,
        agent_decision: str,
        rationale: str,
        decision_confidence: int = 80,
        approved_amount: float | None = None,
        denial_reason: str | None = None,
    ) -> dict[str, Any]:
        agent_decision = agent_decision.lower()
        if agent_decision not in {"approve", "deny"}:
            raise ValueError("agent_decision must be 'approve' or 'deny'")
        payload = {
            "agent_decision": agent_decision,
            "decision_confidence": max(0, min(100, decision_confidence)),
            "decision_rationale": rationale,
        }
        if agent_decision == "approve":
            payload["approved_amount"] = approved_amount
        else:
            payload["denial_reason"] = denial_reason or "not_specified"
        return payload

    @kernel_function(name="validate_handoff_schema", description="Validate payload keys against schema metadata")
    async def validate_handoff_schema(self, payload: Dict[str, Any] | str) -> dict[str, Any]:
        data = _ensure_dict(payload)
        required = self._schema.get("required", [])
        missing = [field for field in required if field not in data]
        return {
            "valid": len(missing) == 0,
            "missing_fields": missing,
            "total_required": len(required),
        }

    @kernel_function(name="package_settlement_payload", description="Create standardized settlement payloads")
    async def package_settlement_payload(
        self,
        context: Dict[str, Any] | str,
        agent_decision: str,
        approved_amount: float | None = None,
        denial_reason: str | None = None,
    ) -> dict[str, Any]:
        ctx = _ensure_dict(context)
        base_payload = {
            "claim_id": ctx.get("claim_id"),
            "policy_number": ctx.get("policy_number"),
            "agent_decision": agent_decision,
            "decision_rationale": ctx.get("decision_rationale"),
            "risk_score": ctx.get("risk_score"),
            "assessment_summary": ctx.get("assessment_summary"),
        }
        if agent_decision == "approve":
            base_payload["payout_amount"] = approved_amount or ctx.get("suggested_payout")
            base_payload["handoff_status"] = "ready_for_settlement"
        else:
            base_payload["denial_reason"] = denial_reason or ctx.get("denial_reason")
            base_payload["handoff_status"] = "denied_with_reason"
        return base_payload


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------


def build_tool_plugins(repo: SharedDataRepository) -> dict[str, object]:
    vendor_tools = VendorTools(repo)
    plugins: dict[str, object] = {
        "PolicyTools": PolicyTools(repo),
        "ClaimsHistoryTools": ClaimsHistoryTools(repo),
        "FraudTools": FraudTools(repo),
        "ExternalSignalsTools": ExternalSignalsTools(repo),
        "VendorTools": vendor_tools,
        "MedicalTools": MedicalTools(repo, vendor_tools),
        "DocumentTools": DocumentTools(repo),
        "HandoffTools": HandoffTools(repo),
    }
    return plugins
