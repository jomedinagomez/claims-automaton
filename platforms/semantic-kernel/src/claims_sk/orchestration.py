"""Core orchestration flow for the Semantic Kernel track."""

from typing import Any, Dict, Optional
import logging
from pathlib import Path
from datetime import datetime

from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent, MagenticOrchestration
from semantic_kernel.contents import ChatHistory
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.utils.author_role import AuthorRole

from .managers import ClaimsMagenticManager
from .session_store import SessionStore

logger = logging.getLogger(__name__)

SPECIALIST_ROLES = {
    "policy_specialist",
    "medical_specialist",
    "fraud_analyst",
    "claims_history_analyst",
    "vendor_specialist",
}


class ClaimsOrchestrator:
    """
    Orchestrates the three-phase claims processing workflow.
    
    Phase 1 (Sequential): Intake acknowledgment and initial policy validation
    Phase 2 (Magentic): Adaptive specialist data gathering with dynamic agent selection
    Phase 3 (Handoff): Assessment synthesis and ClaimsOfficer decision capture
    
    Attributes:
        kernel: Semantic Kernel instance with Azure OpenAI configuration
        agents: Dictionary of specialist agents keyed by role
        manager: Custom ClaimsMagenticManager for termination policy
        context: Shared metadata state mirroring BPMN tokens
    """
    
    def __init__(
        self,
        kernel: Kernel,
        agents: Dict[str, ChatCompletionAgent],
        max_rounds: int = 15,
        stall_threshold: int = 3,
        enable_human_in_loop: bool = True,
        debug_log_dir: Optional[Path] = None,
        session_store: Optional[SessionStore] = None,
    ):
        """
        Initialize the orchestrator with kernel, agents, and termination policies.
        
        Args:
            kernel: Configured Semantic Kernel instance
            agents: Dictionary mapping agent roles to ChatCompletionAgent instances
            max_rounds: Maximum orchestration iterations before forced termination
            stall_threshold: Number of consecutive stalled iterations before exit
            enable_human_in_loop: Whether to pause for operator approval on missing data
            debug_log_dir: Optional directory for agent trace logs
            session_store: Optional SessionStore for persistence (auto-created if None)
        """
        self.kernel = kernel
        self.agents = agents
        self.max_rounds = max_rounds
        self.enable_human_in_loop = enable_human_in_loop
        self.debug_log_dir = Path(debug_log_dir) if debug_log_dir else Path("output") / "agent_traces"
        self._debug_log_path: Optional[Path] = None
        self.session_store = session_store or SessionStore()
        
        # Get the chat completion service from kernel
        service = self.kernel.get_service()
        
        self.manager = ClaimsMagenticManager(
            chat_completion_service=service,
            max_rounds=max_rounds,
            stall_threshold=stall_threshold,
            enable_human_in_loop=enable_human_in_loop,
        )
        
        self._magentic_orchestration: Optional[MagenticOrchestration] = None
        self.context: Dict[str, Any] = {}  # Current processing context
        
        logger.info(
            "ClaimsOrchestrator initialized with %d agents, max_rounds=%d, stall_threshold=%d, session_persistence=%s",
            len(agents),
            max_rounds,
            stall_threshold,
            "enabled" if session_store else "disabled",
        )
    
    async def process_claim(
        self,
        claim_data: Dict[str, Any],
        chat_history: Optional[ChatHistory] = None,
        existing_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute the three-phase claims orchestration workflow.
        
        Args:
            claim_data: Raw claim submission data (customer info, incident details, documents)
            chat_history: Optional existing conversation history for continuation
            existing_context: Optional existing context for session resume
        
        Returns:
            Dictionary containing orchestration result with keys:
                - status: "approved" | "denied" | "stalled" | "timeout" | "paused"
                - termination_reason: Why the orchestration ended
                - context: Final metadata state
                - handoff_payload: Settlement or denial package (if applicable)
                - chat_history: Complete conversation record
        """
        self.manager.reset()
        context = self._bootstrap_context(claim_data, existing_context)
        self._initialize_debug_log(context)
        chat_history = chat_history or ChatHistory()

        missing_docs = [doc for doc in context.get("missing_documents", []) if doc]
        if missing_docs:
            system_note = "\n".join([
                "System note: The intake portal did not find these referenced documents.",
                "Please instruct the customer to upload them before the claim can proceed:",
                *[f"- {doc}" for doc in missing_docs],
            ])
            chat_history.add_message(
                ChatMessageContent(
                    role=AuthorRole.SYSTEM,
                    content=system_note,
                )
            )
        
        claim_id = context.get("claim_id", "UNKNOWN")
        
        logger.info(
            "Starting claims orchestration for claim_id=%s, policy_number=%s, resume=%s",
            claim_id,
            context.get("policy_number"),
            existing_context is not None,
        )
        
        try:
            await self._phase1_sequential_intake(context, chat_history)
            
            # Save session after Phase 1 if paused
            if self._should_pause(context):
                await self._save_session_snapshot(claim_id, chat_history, context, "paused_after_phase1")
                result = self._create_paused_result(context, chat_history)
                logger.info(
                    "Claims orchestration paused for claim_id=%s, missing_documents=%d",
                    claim_id,
                    len(context.get("missing_documents", [])),
                )
                return result
            
            if not self.manager.should_terminate(context):
                await self._phase2_magentic_gathering(context, chat_history)
            
            # Save session after Phase 2 if paused
            if self._should_pause(context):
                await self._save_session_snapshot(claim_id, chat_history, context, "paused_after_phase2")
                result = self._create_paused_result(context, chat_history)
                logger.info(
                    "Claims orchestration paused for claim_id=%s, missing_documents=%d",
                    claim_id,
                    len(context.get("missing_documents", [])),
                )
                return result
            
            if not self.manager.should_terminate(context):
                await self._phase3_handoff_decision(context, chat_history)
            
            result = self.manager.gather_final_result(context, chat_history)
            
            # Archive completed session
            await self._archive_completed_session(claim_id, chat_history, context, result)
            
            logger.info(
                "Claims orchestration completed for claim_id=%s, status=%s, termination_reason=%s",
                claim_id,
                result["status"],
                result["termination_reason"],
            )
            
            return result
        
        except Exception as e:
            logger.error(
                "Claims orchestration failed for claim_id=%s: %s",
                claim_id,
                str(e),
                exc_info=True,
            )
            # Save error state
            await self._save_session_snapshot(claim_id, chat_history, context, "error")
            return {
                "status": "error",
                "termination_reason": "exception",
                "error": str(e),
                "context": context,
                "chat_history": chat_history,
            }
    
    async def _phase1_sequential_intake(
        self,
        context: Dict[str, Any],
        chat_history: ChatHistory,
    ) -> None:
        """
        Phase 1: Deterministic intake acknowledgment and initial validation.
        
        Executes sequential steps:
        1. Send acknowledgment to customer
        2. Validate policy status
        3. Initial coverage check
        4. Document completeness assessment
        
        Updates context with validation results and missing documents list.
        """
        logger.info("Phase 1: Sequential intake started for claim_id=%s", context["claim_id"])
        
        # Add the original claim content as the first user message for agents to analyze
        if "original_content" in context:
            user_message = ChatMessageContent(
                role=AuthorRole.USER,
                content=f"New claim submission:\n\n{context['original_content']}"
            )
            chat_history.add_message(user_message)
        
        if await self._invoke_agent("intake_coordinator", chat_history):
            context["ack_sent"] = True
        
        await self._invoke_agent("policy_specialist", chat_history)
        await self._invoke_agent("document_validator", chat_history)
        context["state"] = "validation_complete"
        
        logger.info(
            "Phase 1 completed for claim_id=%s, missing_documents=%d",
            context["claim_id"],
            len(context.get("missing_documents", [])),
        )
    
    async def _phase2_magentic_gathering(
        self,
        context: Dict[str, Any],
        chat_history: ChatHistory,
    ) -> None:
        """
        Phase 2: Adaptive specialist data gathering via manual coordination.
        
        Coordinates specialist agents to gather evidence, validate data,
        and build comprehensive claim assessment. The custom manager
        (ClaimsMagenticManager) decides when gathering is complete based
        on BPMN-aligned termination logic.
        """
        logger.info("Phase 2: Magentic gathering started for claim_id=%s", context["claim_id"])
        
        # Check if missing information or documents requires human input
        if context.get("missing_documents") or context.get("missing_information"):
            missing_items = []
            if context.get("missing_information"):
                missing_items.extend(context["missing_information"])
            if context.get("missing_documents"):
                missing_items.extend(context["missing_documents"])
            logger.info(
                "Skipping Phase 2: claim_id=%s has missing items: %s",
                context["claim_id"],
                missing_items
            )
            context["handoff_payload"] = {
                "decision": "PENDING",
                "notes": f"Awaiting required information/documents from claimant: {', '.join(missing_items)}",
            }
            return context
        
        context["state"] = "adaptive_gathering"
        
        # Get specialist agents for adaptive gathering
        specialists = [
            self.agents[role] for role in SPECIALIST_ROLES if role in self.agents
        ]
        
        if not specialists:
            logger.warning("No specialist agents available for Phase 2")
            return
        
        round_count = 0
        
        logger.info(
            "Phase 2: Starting with %d specialists for claim_id=%s",
            len(specialists),
            context["claim_id"],
        )
        
        while True:
            if self.manager.should_terminate(context):
                break
            
            round_count += 1
            logger.debug(
                "Magentic round %d/%d for claim_id=%s",
                round_count,
                self.max_rounds,
                context["claim_id"],
            )
            
            # Invoke each specialist with current conversation context
            for agent in specialists:
                self._log_agent_input(agent.name, chat_history)
                response = None
                async for item in agent.invoke(messages=chat_history.messages):
                    response = item.message
                if response:
                    chat_history.add_message(response)
                    self._log_agent_output(agent.name, response)
                    logger.debug(
                        "Specialist %s contributed to claim_id=%s",
                        agent.name,
                        context["claim_id"],
                    )
            
            self.manager.record_round()
            
            if self.enable_human_in_loop and context.get("missing_documents"):
                logger.info(
                    "Pausing for human input: claim_id=%s missing=%s",
                    context["claim_id"],
                    context["missing_documents"],
                )
                break
        
        context["state"] = "data_gathering_complete"
        logger.info(
            "Phase 2 completed for claim_id=%s, rounds=%d, risk_score=%d",
            context["claim_id"],
            round_count,
            context.get("risk_score", 0),
        )
    
    async def _phase3_handoff_decision(
        self,
        context: Dict[str, Any],
        chat_history: ChatHistory,
    ) -> None:
        """
        Phase 3: Assessment synthesis and ClaimsOfficer decision capture.
        
        Sequential steps:
        1. AssessmentAgent synthesizes all gathered data into brief
        2. ClaimsOfficer agent reviews brief and makes approval/denial decision
        3. HandoffAgent packages settlement or denial payload
        
        Updates context with agent_decision, decision_confidence, handoff_status.
        """
        logger.info("Phase 3: Handoff decision started for claim_id=%s", context["claim_id"])
        await self._invoke_agent("assessment_agent", chat_history)
        await self._invoke_agent("claims_officer", chat_history)
        if await self._invoke_agent("handoff_agent", chat_history):
            context["handoff_status"] = "ready_for_settlement"
        
        logger.info(
            "Phase 3 completed for claim_id=%s, agent_decision=%s, handoff_status=%s",
            context["claim_id"],
            context.get("agent_decision"),
            context.get("handoff_status"),
        )

    def _bootstrap_context(
        self,
        claim_data: Dict[str, Any],
        existing_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        base = {
            "state": "intake",
            "missing_documents": [],
            "risk_score": 0,
            "fraud_indicators": [],
            "assessment_confidence": 0,
            "agent_decision": None,
            "decision_confidence": 0,
            "ack_sent": False,
            "info_request_sent": False,
            "sla_breached": False,
            "agent_reviewed": False,
            "handoff_status": "pending",
            "denial_package_ready": False,
        }
        base.update(claim_data)
        if existing_context:
            base.update(existing_context)
        return base

    async def _invoke_agent(self, role: str, chat_history: ChatHistory):
        agent = self.agents.get(role)
        if not agent:
            logger.debug("Agent %s not configured", role)
            return None
        self._log_agent_input(role, chat_history)
        response = None
        async for item in agent.invoke(messages=chat_history.messages):
            response = item.message
        if response:
            chat_history.add_message(response)
            self._log_agent_output(role, response)
        return response

    def _ensure_magentic_orchestration(self) -> Optional[MagenticOrchestration]:
        if self._magentic_orchestration:
            return self._magentic_orchestration
        specialists = [
            agent for role, agent in self.agents.items() if role in SPECIALIST_ROLES
        ]
        if not specialists:
            logger.warning("No specialist agents available for Magentic phase")
            return None
        self._magentic_orchestration = MagenticOrchestration(
            members=specialists,
            manager=self.manager,
        )
        return self._magentic_orchestration

    def _initialize_debug_log(self, context: Dict[str, Any]) -> None:
        if not self.debug_log_dir:
            self._debug_log_path = None
            return
        self.debug_log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.debug_log_dir / f"{context['claim_id']}_trace.txt"
        header = (
            f"Claims orchestration trace\n"
            f"Claim ID: {context['claim_id']}\n"
            f"Policy: {context.get('policy_number', 'unknown')}\n"
            f"Generated: {datetime.utcnow().isoformat()}Z\n"
            f"{'-' * 60}\n"
        )
        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write(header)
        self._debug_log_path = log_path
        context["debug_log_path"] = str(log_path)

    def _log_agent_input(self, agent_name: str, chat_history: ChatHistory) -> None:
        if not self._debug_log_path:
            return
        transcript = self._render_chat_history(chat_history)
        timestamp = datetime.utcnow().isoformat() + "Z"
        with self._debug_log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp}] {agent_name} INPUT\n{transcript}\n\n")

    def _log_agent_output(self, agent_name: str, message: Optional[ChatMessageContent]) -> None:
        if not self._debug_log_path or not message:
            return
        timestamp = datetime.utcnow().isoformat() + "Z"
        payload = self._render_message_text(message)
        with self._debug_log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp}] {agent_name} OUTPUT\n{payload}\n\n")

    @staticmethod
    def _render_message_text(message: ChatMessageContent) -> str:
        if getattr(message, "content", None):
            return str(message.content).strip()
        items = getattr(message, "items", None)
        if items:
            parts = []
            for item in items:
                text = getattr(item, "text", None)
                if text:
                    parts.append(text)
            if parts:
                return "\n".join(parts).strip()
        return str(message).strip()

    @staticmethod
    def _render_chat_history(chat_history: ChatHistory) -> str:
        lines = []
        for idx, message in enumerate(chat_history.messages, start=1):
            role = getattr(message, "role", "unknown")
            payload = ClaimsOrchestrator._render_message_text(message)
            lines.append(f"{idx:02d}. {role}: {payload}")
        return "\n".join(lines)
    
    def _should_pause(self, context: Dict[str, Any]) -> bool:
        """
        Determine if orchestration should pause for missing documents.
        
        Args:
            context: Current orchestration context
        
        Returns:
            True if human-in-loop is enabled and documents are missing
        """
        return (
            self.enable_human_in_loop 
            and len(context.get("missing_documents", [])) > 0
        )
    
    def _create_paused_result(
        self,
        context: Dict[str, Any],
        chat_history: ChatHistory,
    ) -> Dict[str, Any]:
        """
        Create result dictionary for paused orchestration.
        
        Args:
            context: Current orchestration context
            chat_history: Current conversation history
        
        Returns:
            Result dictionary with paused status
        """
        return {
            "status": "paused",
            "termination_reason": "missing_documents",
            "context": context,
            "chat_history": chat_history,
            "missing_documents": context.get("missing_documents", []),
            "resume_instructions": (
                f"To resume claim {context.get('claim_id')}, provide the missing documents "
                f"and call continue_claim() with the claim_id and updated documents."
            ),
        }
    
    async def _save_session_snapshot(
        self,
        claim_id: str,
        chat_history: ChatHistory,
        context: Dict[str, Any],
        status: str,
    ) -> None:
        """
        Save current session state to persistent storage.
        
        Args:
            claim_id: Unique claim identifier
            chat_history: Current conversation history
            context: Current orchestration context
            status: Session status (paused_after_phase1, paused_after_phase2, error)
        """
        if not self.session_store:
            logger.debug("Session persistence disabled, skipping save")
            return
        
        metadata = {
            "status": status,
            "paused_at": datetime.utcnow().isoformat() + "Z",
        }
        
        self.session_store.save_session(
            claim_id=claim_id,
            chat_history=chat_history,
            context=context,
            metadata=metadata,
        )
    
    async def _archive_completed_session(
        self,
        claim_id: str,
        chat_history: ChatHistory,
        context: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        """
        Archive completed session with final result.
        
        Args:
            claim_id: Unique claim identifier
            chat_history: Final conversation history
            context: Final orchestration context
            result: Final orchestration result
        """
        if not self.session_store:
            logger.debug("Session persistence disabled, skipping archive")
            return
        
        metadata = {
            "status": "completed",
            "final_status": result.get("status"),
            "termination_reason": result.get("termination_reason"),
            "completed_at": datetime.utcnow().isoformat() + "Z",
        }
        
        self.session_store.save_session(
            claim_id=claim_id,
            chat_history=chat_history,
            context=context,
            metadata=metadata,
        )
        
        self.session_store.archive_session(claim_id)
    
    async def continue_claim(
        self,
        claim_id: str,
        additional_documents: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Continue processing a paused claim after receiving missing evidence.
        
        Args:
            claim_id: Unique claim identifier
            additional_documents: Newly provided evidence (files or inline notes) to resolve missing requirements
        
        Returns:
            Orchestration result (same format as process_claim)
        
        Raises:
            ValueError: If session not found or not in paused state
        """
        if not self.session_store or not self.session_store.session_exists(claim_id):
            raise ValueError(f"No saved session found for claim_id: {claim_id}")
        
        # Load saved session
        session_data = self.session_store.load_session(claim_id)
        chat_history = session_data["chat_history"]
        context = session_data["context"]
        
        logger.info(
            "Resuming claim orchestration: claim_id=%s, messages=%d",
            claim_id,
            len(chat_history.messages),
        )
        
        # Update context with new documents
        if additional_documents:
            new_documents = additional_documents.get("documents", [])
            if new_documents:
                context.setdefault("documents", []).extend(new_documents)

            notes = additional_documents.get("notes", [])
            if notes:
                context.setdefault("customer_notes", []).extend(notes)
                for note in notes:
                    chat_history.add_message(
                        ChatMessageContent(
                            role=AuthorRole.USER,
                            content=f"Customer provided additional details for {note.get('type')}: {note.get('content')}",
                        )
                    )

            provided_types = {
                doc.get("type")
                for doc in new_documents
                if doc.get("type")
            }
            provided_types.update(
                note.get("type")
                for note in notes
                if note.get("type")
            )

            if provided_types:
                context["missing_documents"] = [
                    doc for doc in context.get("missing_documents", [])
                    if doc not in provided_types
                ]
                chat_history.add_message(
                    ChatMessageContent(
                        role=AuthorRole.SYSTEM,
                        content=(
                            "Customer has provided additional evidence for: "
                            + ", ".join(sorted(provided_types))
                        ),
                    )
                )
        
        # Resume processing from saved state
        claim_data = {
            "claim_id": claim_id,
            "policy_number": context.get("policy_number"),
            "claimant_name": context.get("claimant_name"),
            "incident_date": context.get("incident_date"),
            "documents": context.get("documents", []),
        }
        
        return await self.process_claim(
            claim_data=claim_data,
            chat_history=chat_history,
            existing_context=context,
        )


async def build_orchestrator(
    kernel: Kernel,
    agents: Dict[str, ChatCompletionAgent],
    config: Optional[Dict[str, Any]] = None,
) -> ClaimsOrchestrator:
    """
    Factory function to build and configure the ClaimsOrchestrator.
    
    Args:
        kernel: Configured Semantic Kernel instance with Azure OpenAI
        agents: Dictionary of specialist agents loaded from agents_config.yaml
        config: Optional configuration overrides for max_rounds, stall_threshold, etc.
    
    Returns:
        Configured ClaimsOrchestrator instance ready to process claims
    """
    config = config or {}
    
    # Initialize session store if session persistence is enabled
    session_store = None
    if config.get("enable_session_persistence", True):
        session_dir = config.get("session_dir")
        session_store = SessionStore(base_dir=Path(session_dir) if session_dir else None)
    
    orchestrator = ClaimsOrchestrator(
        kernel=kernel,
        agents=agents,
        max_rounds=config.get("max_rounds", 15),
        stall_threshold=config.get("stall_threshold", 3),
        enable_human_in_loop=config.get("enable_human_in_loop", True),
        debug_log_dir=Path(config.get("debug_log_dir")) if config.get("debug_log_dir") else None,
        session_store=session_store,
    )
    logger.info("ClaimsOrchestrator built with %d agents", len(agents))
    return orchestrator
