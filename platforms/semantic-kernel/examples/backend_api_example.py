"""
Example: Backend API pattern for claims orchestration with session persistence.

This demonstrates how a FastAPI/Flask backend would integrate the orchestrator
with proper session management for pause/resume workflows.

Key patterns:
- POST /claims - Submit new claim
- GET /claims/{claim_id} - Get claim status
- POST /claims/{claim_id}/continue - Resume with additional documents
- GET /claims/{claim_id}/missing-documents - List missing requirements
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from claims_sk.runtime import create_runtime


class ClaimsBackendService:
    """
    Backend service layer for claims orchestration.
    
    In a real API, this would be injected as a dependency into FastAPI routes.
    """
    
    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize backend service.
        
        Args:
            config_dir: Path to configuration directory
        """
        self.config_dir = config_dir
        self.runtime = None
        self.orchestrator = None
    
    async def initialize(self):
        """Bootstrap runtime and orchestrator (call during API startup)."""
        self.runtime = await create_runtime(config_dir=self.config_dir)
        self.orchestrator = self.runtime.get_orchestrator()
    
    async def submit_claim(self, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit new claim for processing.
        
        Args:
            claim_data: Claim submission data from frontend
        
        Returns:
            Orchestration result with status, missing_documents, etc.
        """
        result = await self.orchestrator.process_claim(claim_data=claim_data)
        
        # Transform result for API response
        response = {
            "claim_id": claim_data.get("claim_id"),
            "status": result["status"],
            "termination_reason": result.get("termination_reason"),
        }
        
        if result["status"] == "paused":
            response["missing_documents"] = result.get("missing_documents", [])
            response["message"] = (
                f"Claim requires {len(result.get('missing_documents', []))} additional documents. "
                f"Please upload them to continue processing."
            )
        elif result["status"] in ("approved", "denied"):
            response["handoff_payload"] = result.get("handoff_payload")
        
        return response
    
    async def get_claim_status(self, claim_id: str) -> Dict[str, Any]:
        """
        Get current status of claim.
        
        Args:
            claim_id: Unique claim identifier
        
        Returns:
            Status information from saved session
        """
        if not self.orchestrator.session_store.session_exists(claim_id):
            return {
                "error": "Claim not found",
                "claim_id": claim_id,
            }
        
        session_data = self.orchestrator.session_store.load_session(claim_id)
        metadata = session_data["metadata"]
        context = session_data["context"]
        
        return {
            "claim_id": claim_id,
            "status": metadata.get("status"),
            "missing_documents": context.get("missing_documents", []),
            "saved_at": metadata.get("saved_at"),
            "message_count": len(session_data["chat_history"].messages),
        }
    
    async def continue_claim(
        self,
        claim_id: str,
        additional_documents: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Continue processing paused claim with additional documents.
        
        Args:
            claim_id: Unique claim identifier
            additional_documents: Newly uploaded documents
        
        Returns:
            Updated orchestration result
        """
        result = await self.orchestrator.continue_claim(
            claim_id=claim_id,
            additional_documents=additional_documents,
        )
        
        # Transform result for API response
        response = {
            "claim_id": claim_id,
            "status": result["status"],
            "termination_reason": result.get("termination_reason"),
        }
        
        if result["status"] == "paused":
            response["missing_documents"] = result.get("missing_documents", [])
            response["message"] = (
                f"Claim still requires {len(result.get('missing_documents', []))} additional documents."
            )
        elif result["status"] in ("approved", "denied"):
            response["handoff_payload"] = result.get("handoff_payload")
            response["message"] = f"Claim processing complete: {result['status']}"
        
        return response
    
    async def list_missing_documents(self, claim_id: str) -> Dict[str, Any]:
        """
        Get list of missing documents for paused claim.
        
        Args:
            claim_id: Unique claim identifier
        
        Returns:
            List of missing document types and descriptions
        """
        if not self.orchestrator.session_store.session_exists(claim_id):
            return {
                "error": "Claim not found",
                "claim_id": claim_id,
            }
        
        session_data = self.orchestrator.session_store.load_session(claim_id)
        context = session_data["context"]
        
        return {
            "claim_id": claim_id,
            "missing_documents": context.get("missing_documents", []),
            "count": len(context.get("missing_documents", [])),
        }


# Example usage showing API-like workflow
async def demo_backend_workflow():
    """
    Demonstrate typical backend API workflow for pause/resume.
    """
    print("=" * 60)
    print("Backend API Workflow Demo")
    print("=" * 60)
    
    # Initialize service (startup event)
    service = ClaimsBackendService()
    await service.initialize()
    print("✓ Backend service initialized")
    
    # 1. Submit new claim (POST /claims)
    print("\n1. Submitting new claim...")
    claim_data = {
        "claim_id": "CLM-DEMO-001",
        "policy_number": "AUTO-123456",
        "claimant_name": "Jane Doe",
        "incident_date": "2025-11-15",
        "incident_description": "Rear-end collision at traffic light",
        "documents": [
            {"type": "police_report", "filename": "police_report.pdf"},
        ],
    }
    
    result = await service.submit_claim(claim_data)
    print(f"   Status: {result['status']}")
    if result["status"] == "paused":
        print(f"   Missing: {result['missing_documents']}")
    
    # 2. Check status (GET /claims/{claim_id})
    print("\n2. Checking claim status...")
    status = await service.get_claim_status("CLM-DEMO-001")
    print(f"   Status: {status['status']}")
    print(f"   Messages: {status['message_count']}")
    
    # 3. Get missing documents (GET /claims/{claim_id}/missing-documents)
    print("\n3. Listing missing documents...")
    missing = await service.list_missing_documents("CLM-DEMO-001")
    print(f"   Required: {missing['count']} documents")
    for doc in missing["missing_documents"]:
        print(f"     - {doc}")
    
    # 4. Upload documents and continue (POST /claims/{claim_id}/continue)
    print("\n4. Uploading additional documents and resuming...")
    additional_docs = {
        "documents": [
            {"type": "vehicle_damage_photos", "filename": "damage_front.jpg"},
            {"type": "insurance_exchange_form", "filename": "exchange.pdf"},
        ]
    }
    
    result = await service.continue_claim("CLM-DEMO-001", additional_docs)
    print(f"   Status: {result['status']}")
    print(f"   Message: {result.get('message')}")
    
    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(demo_backend_workflow())
