"""Agent factory + YAML loader used by the Semantic Kernel track."""

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior

logger = logging.getLogger(__name__)


@dataclass
class AgentDefinition:
    role: str
    name: str
    instructions: str
    tools: List[str]
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentDefinition":
        role = data.get("role")
        instructions = data.get("instructions")
        if not role or not instructions:
            raise ValueError(f"Agent config missing role or instructions: {data}")
        
        # Use first line of instructions as description if not provided
        description = data.get("description")
        if not description and instructions:
            description = instructions.split('\n')[0].strip()
        
        return cls(
            role=role,
            name=data.get("name", role.title()),
            instructions=instructions,
            tools=data.get("tools", []),
            description=description,
        )


class AgentFactory:
    """
    Factory for loading and instantiating specialist agents.
    
    Loads agent definitions from YAML configuration and creates
    ChatCompletionAgent instances with Azure OpenAI connections.
    
    Attributes:
        config_path: Path to agents_config.yaml
        kernel: Semantic Kernel instance with Azure OpenAI service
        agents: Dictionary of instantiated agents keyed by role
    """
    
    def __init__(self, config_path: Path, kernel: Kernel):
        """
        Initialize the agent factory.
        
        Args:
            config_path: Path to agents_config.yaml
            kernel: Configured Semantic Kernel instance
        """
        self.config_path = config_path
        self.kernel = kernel
        self.agents: Dict[str, ChatCompletionAgent] = {}
        
        logger.info("AgentFactory initialized with config_path=%s", config_path)
    
    def load_agents(self) -> Dict[str, ChatCompletionAgent]:
        """
        Load all agents from configuration file.
        
        Returns:
            Dictionary mapping agent roles to ChatCompletionAgent instances
        
        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid or missing required fields
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Agent config not found: {self.config_path}")
        
        logger.info("Loading agents from config: %s", self.config_path)
        
        definitions = self._load_definitions()
        for definition in definitions:
            agent = self._create_agent(definition)
            self.agents[definition.role] = agent
            logger.debug("Loaded agent: role=%s, name=%s", definition.role, definition.name)
        
        logger.info("Loaded %d agents successfully", len(self.agents))
        return self.agents

    def _load_definitions(self) -> List[AgentDefinition]:
        with open(self.config_path, "r", encoding="utf-8") as stream:
            config = yaml.safe_load(stream) or {}
        agents = config.get("agents", [])
        if not agents:
            raise ValueError("Invalid config: missing 'agents' section")
        return [AgentDefinition.from_dict(entry) for entry in agents]

    def _create_agent(self, definition: AgentDefinition) -> ChatCompletionAgent:
        """
        Create a single ChatCompletionAgent from configuration.
        
        Args:
            agent_def: Agent definition from YAML with keys:
                - role: Unique identifier (e.g., "intake_coordinator")
                - name: Display name
                - instructions: System prompt
                - tools: List of tool names (optional)
                - model: Model override (optional)
        
        Returns:
            Configured ChatCompletionAgent instance
        """
        # Get the service from kernel
        service = self.kernel.get_service()
        
        agent = ChatCompletionAgent(
            service=service,
            kernel=self.kernel,
            name=definition.name,
            instructions=definition.instructions,
            description=definition.description or definition.instructions.split('\n')[0].strip(),
        )
        
        # Attach tools if specified
        if definition.tools:
            self._attach_tools(agent, definition.tools)
        
        logger.debug(
            "Created agent: role=%s, name=%s, tools=%d",
            definition.role,
            definition.name,
            len(definition.tools),
        )
        
        return agent
    
    def _attach_tools(self, agent: ChatCompletionAgent, tool_names: List[str]) -> None:
        """
        Attach tools to agent from kernel plugin registry.
        
        Args:
            agent: ChatCompletionAgent instance
            tool_names: List of tool/function names to attach
        """
        if not tool_names:
            return
        metadata = self.kernel.get_full_list_of_function_metadata()
        name_to_fqn: Dict[str, List[str]] = {}
        for item in metadata:
            name_to_fqn.setdefault(item.name, []).append(item.fully_qualified_name)

        included: List[str] = []
        for tool in tool_names:
            candidates = name_to_fqn.get(tool)
            if not candidates:
                logger.warning("Tool %s requested by agent %s not found in kernel plugins", tool, agent.name)
                continue
            included.append(candidates[0])

        if not included:
            return

        agent.function_choice_behavior = FunctionChoiceBehavior.Auto(
            filters={"included_functions": included}
        )
        logger.debug(
            "Attached %d tools to agent %s", len(included), agent.name
        )
    
    def get_agent(self, role: str) -> Optional[ChatCompletionAgent]:
        """
        Retrieve an agent by role identifier.
        
        Args:
            role: Agent role key (e.g., "intake_coordinator")
        
        Returns:
            ChatCompletionAgent instance or None if not found
        """
        return self.agents.get(role)
    
    def list_agents(self) -> List[str]:
        """
        List all loaded agent roles.
        
        Returns:
            List of agent role identifiers
        """
        return list(self.agents.keys())


def load_agent_config(config_path: Path, kernel: Kernel) -> Dict[str, ChatCompletionAgent]:
    """
    Convenience function to load agents from configuration.
    
    Args:
        config_path: Path to agents_config.yaml
        kernel: Configured Semantic Kernel instance
    
    Returns:
        Dictionary mapping agent roles to ChatCompletionAgent instances
    """
    factory = AgentFactory(config_path, kernel)
    return factory.load_agents()


# Default agent configuration template (for documentation/scaffolding)
DEFAULT_AGENT_CONFIG = """
# Claims Orchestration Agent Configuration
# Defines specialist agents for the three-phase workflow

agents:
  - role: intake_coordinator
    name: "Intake Coordinator"
    instructions: |
      You are the Intake Coordinator for an insurance claims processing system.
      Your responsibilities:
      1. Acknowledge receipt of the claim submission
      2. Extract claim type from the submission (auto_collision, auto_comprehensive, home_fire, health_surgery)
      3. Use check_information_completeness tool to identify missing information
      4. If information is missing, ask the customer conversationally for the missing details
      5. Once all information is collected, use check_document_completeness to verify documents
      6. If documents are missing, request them from the customer
      7. Update context with validation results
      
      IMPORTANT: Ask for INFORMATION first (data fields), then DOCUMENTS second.
      
      Be conversational and friendly. Instead of asking one question at a time, you can group
      related questions together. For example:
      "I need a few more details:
       1. What is the total amount you're claiming?
       2. Can you describe the damage to your vehicle?
       3. What is the estimated repair cost?"
      
      When information is missing, set context['missing_information'] with the list of what's needed.
      When documents are missing, set context['missing_documents'] with the list of what's needed.
      
      Always respond with structured output containing:
      - ack_sent: boolean
      - policy_valid: boolean
      - claim_type: string
      - missing_information: list of missing data fields
      - missing_documents: list of missing document files
      - next_step: string
    tools:
      - validate_policy_status
      - check_information_completeness
      - check_document_completeness
  
  - role: policy_specialist
    name: "Policy Specialist"
    instructions: |
      You are a Policy Specialist for insurance claims.
      Your responsibilities:
      1. Verify policy status (active, lapsed, expired)
      2. Check coverage limits and deductibles
      3. Validate claim type is covered under policy tier
      4. Identify any exclusions that apply
      5. Calculate remaining aggregate limit
      
      Always respond with structured output containing:
      - policy_status: string
      - coverage_valid: boolean
      - coverage_limit: number
      - deductible: number
      - exclusions: list of strings
      - remaining_aggregate: number
    tools:
      - lookup_policy_details
      - check_coverage_matrix
  
  - role: medical_specialist
    name: "Medical Claims Specialist"
    instructions: |
      You are a Medical Claims Specialist.
      Your responsibilities:
      1. Validate medical codes (ICD-10, CPT)
      2. Verify provider credentials
      3. Check treatment necessity and reasonableness
      4. Identify any pre-existing conditions
      5. Validate medical documentation completeness
      
      Only invoke if claim_type is health-related.
    tools:
      - validate_medical_codes
      - verify_provider_credentials
  
  - role: fraud_analyst
    name: "Fraud Detection Analyst"
    instructions: |
      You are a Fraud Detection Analyst.
      Your responsibilities:
      1. Check for blacklisted entities (customer, provider, vendor)
      2. Detect duplicate claims or suspicious patterns
      3. Verify incident corroboration (police reports, witnesses)
      4. Flag inconsistent statements or timelines
      5. Calculate fraud risk score
      
      Always respond with structured output containing:
      - fraud_indicators: list of strings
      - risk_score: integer (0-100)
      - blacklist_hit: boolean
      - recommendation: string
    tools:
      - check_blacklist
      - detect_duplicate_claims
      - verify_police_report
      - check_weather_events
  
  - role: claims_history_analyst
    name: "Claims History Analyst"
    instructions: |
      You are a Claims History Analyst.
      Your responsibilities:
      1. Lookup customer's prior claims
      2. Calculate claim frequency metrics
      3. Identify patterns of high-risk behavior
      4. Check for prior fraud flags
      5. Update risk score based on history
    tools:
      - lookup_claims_history
      - calculate_frequency_metrics
  
  - role: vendor_specialist
    name: "Vendor Verification Specialist"
    instructions: |
      You are a Vendor Verification Specialist.
      Your responsibilities:
      1. Verify repair shop or service provider credentials
      2. Check vendor pricing against market rates
      3. Validate estimates and invoices
      4. Flag overpriced or suspicious vendors
      
      Only invoke if claim involves third-party vendors.
    tools:
      - verify_vendor_credentials
      - validate_vendor_pricing
  
  - role: document_validator
    name: "Document Validation Specialist"
    instructions: |
      You are a Document Validation Specialist.
      Your responsibilities:
      1. Check for required documents (police report, estimates, receipts, photos)
      2. Validate document authenticity and completeness
      3. Extract key information from documents
      4. Identify missing or incomplete evidence
      5. Request additional information if needed
      
      Always respond with structured output containing:
      - missing_documents: list of strings
      - document_completeness_score: integer (0-100)
      - info_request_sent: boolean
    tools:
      - extract_document_metadata
      - validate_document_authenticity
  
  - role: assessment_agent
    name: "Assessment Agent"
    instructions: |
      You are an Assessment Agent that synthesizes all gathered data.
      Your responsibilities:
      1. Review all specialist findings (policy, fraud, history, documents)
      2. Synthesize a comprehensive assessment brief
      3. Calculate overall confidence score
      4. Recommend approve/deny with rationale
      5. Prepare context for ClaimsOfficer decision
      
      Always respond with structured output containing:
      - assessment_summary: string
      - assessment_confidence: integer (0-100)
      - recommendation: "approve" | "deny" | "needs_review"
      - key_factors: list of strings
      - suggested_payout: number (if approve)
    tools: []
  
  - role: claims_officer
    name: "Claims Officer (Human-in-Loop)"
    instructions: |
      You are a Claims Officer agent that facilitates human decision capture.
      Your responsibilities:
      1. Present the assessment brief to the human claims agent
      2. Capture their approval/denial decision
      3. Record decision rationale and confidence
      4. Validate decision completeness
      5. Update context with agent_decision metadata
      
      Always respond with structured output containing:
      - agent_decision: "approve" | "deny"
      - decision_confidence: integer (0-100)
      - decision_rationale: string
      - approved_amount: number (if approve)
      - denial_reason: string (if deny)
    tools:
      - capture_human_decision
  
  - role: handoff_agent
    name: "Handoff Payload Agent"
    instructions: |
      You are a Handoff Payload Agent that packages final results.
      Your responsibilities:
      1. Format settlement or denial payload per handoff_schema.json
      2. Include all required fields (claim_id, decision, payout_amount, rationale)
      3. Attach evidence documents
      4. Validate payload against schema
      5. Update context with handoff_status = "ready_for_settlement"
      
      Always respond with structured output matching handoff_schema.json.
    tools:
      - validate_handoff_schema
      - package_settlement_payload
"""


def generate_default_config(output_path: Path) -> None:
    """
    Generate default agents_config.yaml template.
    
    Args:
        output_path: Path where config should be written
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(DEFAULT_AGENT_CONFIG.strip())
    
    logger.info("Generated default agent config: %s", output_path)
