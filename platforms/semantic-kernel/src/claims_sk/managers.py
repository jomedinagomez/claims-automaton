"""Custom Magentic manager with BPMN-aligned termination logic."""

import logging
from typing import Any, Dict, List, Optional

from semantic_kernel.agents import StandardMagenticManager
from semantic_kernel.contents import ChatHistory

logger = logging.getLogger(__name__)


class ClaimsMagenticManager(StandardMagenticManager):
    """
    Custom Magentic manager for claims orchestration with BPMN-aligned termination.
    
    Extends StandardMagenticManager to implement domain-specific termination logic:
    - Checks agent_decision, handoff_status, denial_package_ready metadata
    - Detects stalls (same agent repeating without progress)
    - Enforces max_rounds limit
    - Supports human-in-loop pauses for missing documents
    
    Attributes:
        max_rounds: Maximum orchestration iterations before forced termination
        stall_threshold: Number of stalled iterations before exit
        enable_human_in_loop: Whether to pause for operator approval
        _round_counter: Current iteration count
        _agent_call_history: Tracks agent invocations for stall detection
        _last_ledger_state: Previous ledger snapshot for progress comparison
    """
    
    def __init__(
        self,
        chat_completion_service,
        max_rounds: int = 15,
        stall_threshold: int = 3,
        enable_human_in_loop: bool = True,
    ):
        """
        Initialize the ClaimsMagenticManager with termination policies.
        
        Args:
            chat_completion_service: The AI service for chat completion
            max_rounds: Maximum orchestration iterations before timeout
            stall_threshold: Consecutive stalled rounds before termination
            enable_human_in_loop: Whether to pause for missing documents
        """
        super().__init__(chat_completion_service=chat_completion_service)
        
        # Set custom attributes using object.__setattr__ to bypass Pydantic validation
        object.__setattr__(self, 'max_rounds', max_rounds)
        object.__setattr__(self, 'stall_threshold', stall_threshold)
        object.__setattr__(self, 'enable_human_in_loop', enable_human_in_loop)
        object.__setattr__(self, '_round_counter', 0)
        object.__setattr__(self, '_last_ledger_state', None)
        
        logger.info(
            "ClaimsMagenticManager initialized: max_rounds=%d, stall_threshold=%d, enable_human_in_loop=%s",
            max_rounds,
            stall_threshold,
            enable_human_in_loop,
        )
    
    def should_terminate(
        self,
        context: Dict[str, Any],
        task_ledger: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Evaluate whether the orchestration should terminate based on BPMN conditions.
        
        Termination conditions (in priority order):
        1. Approved and handoff ready: agent_decision == "approve" AND handoff_status == "ready_for_settlement"
        2. Denied (manual): agent_decision == "deny" AND denial_package_ready == True
        3. Denied (SLA breach): sla_breached == True
        4. Stalled: same agent repeating >= stall_threshold with no progress
        5. Max rounds exceeded: round_counter >= max_rounds
        6. Human-in-loop pause: missing_documents != [] AND enable_human_in_loop
        
        Args:
            context: Shared metadata state (BPMN tokens)
            task_ledger: Optional ledger of agent invocations and results
        
        Returns:
            True if orchestration should terminate, False to continue
        """
        if self._signal_if(context, "approved_handoff_ready", self._is_ready_for_handoff(context)):
            return True
        if self._signal_if(context, "denied_manual", self._is_manual_denial(context)):
            return True
        if self._signal_if(context, "denied_sla_breach", context.get("sla_breached")):
            context.setdefault("agent_decision", "deny")
            return True
        if task_ledger and self._signal_if(context, "stalled", self._is_stalled(task_ledger)):
            return True
        if self._signal_if(context, "max_rounds_exceeded", self.rounds_exhausted()):
            return True
        
        # Terminate if missing information or documents detected
        if self.enable_human_in_loop and (context.get("missing_documents") or context.get("missing_information")) and not context.get("agent_reviewed"):
            self._set_reason(context, "human_in_loop_required")
            missing_items = context.get("missing_documents", []) + context.get("missing_information", [])
            logger.info(
                "Termination: Human-in-loop pause required for missing items: %s (claim_id=%s)",
                missing_items,
                context.get("claim_id"),
            )
            return True
        
        # Continue orchestration
        logger.debug(
            "Orchestration continues: round=%d/%d (claim_id=%s)",
            self._round_counter,
            self.max_rounds,
            context.get("claim_id"),
        )
        return False
    
    def _is_stalled(self, task_ledger: List[Dict[str, Any]]) -> bool:
        """
        Detect if orchestration is stalled (no progress for N consecutive iterations).
        
        Stall indicators:
        - Same agent invoked >= stall_threshold times consecutively
        - Ledger state unchanged for >= stall_threshold rounds
        
        Args:
            task_ledger: List of agent invocations with metadata
        
        Returns:
            True if stall detected, False otherwise
        """
        if not task_ledger or len(task_ledger) < self.stall_threshold:
            return False
        
        # Check last N entries for repeated agent calls
        recent_agents = [entry.get("agent_name") for entry in task_ledger[-self.stall_threshold:]]
        if len(set(recent_agents)) == 1:
            logger.debug("Stall detected: agent %s repeated %d times", recent_agents[0], self.stall_threshold)
            return True
        
        current_state = self._extract_ledger_state(task_ledger[-1])
        if self._last_ledger_state and current_state == self._last_ledger_state:
            logger.debug("Stall detected: ledger state unchanged for %d rounds", self.stall_threshold)
            return True
        
        self._last_ledger_state = current_state
        return False

    def _is_ready_for_handoff(self, context: Dict[str, Any]) -> bool:
        return (
            context.get("agent_decision") == "approve"
            and context.get("handoff_status") == "ready_for_settlement"
        )

    def _is_manual_denial(self, context: Dict[str, Any]) -> bool:
        return (
            context.get("agent_decision") == "deny"
            and context.get("denial_package_ready") is True
        )
    
    def _extract_ledger_state(self, ledger_entry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract comparable state from ledger entry (excluding timestamps).
        
        Args:
            ledger_entry: Single ledger record with agent invocation metadata
        
        Returns:
            Dictionary of state fields for comparison
        """
        return {
            "agent_name": ledger_entry.get("agent_name"),
            "result_summary": ledger_entry.get("result_summary"),
            "metadata": ledger_entry.get("metadata", {}),
        }
    
    def gather_final_result(
        self,
        context: Dict[str, Any],
        chat_history: ChatHistory,
    ) -> Dict[str, Any]:
        """
        Format the final orchestration result based on termination condition.
        
        Packages the result with appropriate status, reason, payload based on
        which termination condition was triggered.
        
        Args:
            context: Final metadata state
            chat_history: Complete conversation record
        
        Returns:
            Dictionary with keys:
                - status: "approved" | "denied" | "stalled" | "timeout" | "paused"
                - termination_reason: Why orchestration ended
                - context: Final metadata state
                - handoff_payload: Settlement or denial package (if applicable)
                - chat_history: Full conversation
        """
        termination_reason = context.get("termination_reason", "unknown")
        
        # Map termination reasons to status codes
        status_map = {
            "approved_handoff_ready": "approved",
            "denied_manual": "denied",
            "denied_sla_breach": "denied",
            "stalled": "stalled",
            "max_rounds_exceeded": "timeout",
            "human_in_loop_required": "paused",
        }
        
        status = status_map.get(termination_reason, "unknown")
        
        result = {
            "status": status,
            "termination_reason": termination_reason,
            "context": context,
            "chat_history": chat_history,
            "rounds_executed": self._round_counter,
        }
        
        # Add handoff payload if approved or denied
        if status == "approved":
            result["handoff_payload"] = self._build_settlement_payload(context)
        elif status == "denied":
            result["handoff_payload"] = self._build_denial_payload(context)
        
        logger.info(
            "Final result gathered: status=%s, termination_reason=%s, rounds=%d (claim_id=%s)",
            status,
            termination_reason,
            self._round_counter,
            context.get("claim_id"),
        )
        
        return result
    
    def _build_settlement_payload(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build settlement handoff payload per handoff_schema.json.
        
        Args:
            context: Final metadata state with approval details
        
        Returns:
            Settlement payload for downstream systems
        """
        return {
            "claim_id": context.get("claim_id"),
            "decision": "approve",
            "payout_amount": context.get("approved_amount"),
            "agent_id": context.get("agent_id"),
            "decision_timestamp": context.get("decision_timestamp"),
            "confidence_score": context.get("decision_confidence", 0),
            "fraud_risk": context.get("risk_score", 0),
            "rationale": context.get("decision_rationale", ""),
            "attachments": context.get("evidence_documents", []),
        }
    
    def _build_denial_payload(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build denial handoff payload per handoff_schema.json.
        
        Args:
            context: Final metadata state with denial details
        
        Returns:
            Denial payload for downstream systems
        """
        # Determine denial reason
        if context.get("sla_breached"):
            denial_reason = "other"
            rationale = "Claim denied due to SLA breach (timeout)"
        else:
            denial_reason = context.get("denial_reason", "other")
            rationale = context.get("decision_rationale", "")
        
        return {
            "claim_id": context.get("claim_id"),
            "decision": "deny",
            "agent_id": context.get("agent_id"),
            "decision_timestamp": context.get("decision_timestamp"),
            "confidence_score": context.get("decision_confidence", 0),
            "fraud_risk": context.get("risk_score", 0),
            "rationale": rationale,
            "attachments": context.get("evidence_documents", []),
            "denial_reason": denial_reason,
        }
    
    def reset(self) -> None:
        """
        Reset the manager state for a new orchestration run.
        
        Clears round counter, agent call history, and ledger state.
        """
        self._round_counter = 0
        self._last_ledger_state = None
        logger.debug("ClaimsMagenticManager state reset")

    def record_round(self) -> None:
        """Register completion of a full specialist round."""
        self._round_counter += 1

    def rounds_exhausted(self) -> bool:
        """Return True when the configured max_rounds has been reached."""
        return self._round_counter >= self.max_rounds

    def _signal_if(self, context: Dict[str, Any], reason: str, condition: bool) -> bool:
        if not condition:
            return False
        self._set_reason(context, reason)
        logger.info("Termination: %s (claim_id=%s)", reason, context.get("claim_id"))
        return True

    @staticmethod
    def _set_reason(context: Dict[str, Any], reason: str) -> None:
        context["termination_reason"] = reason
