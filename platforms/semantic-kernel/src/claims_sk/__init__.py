"""
Semantic Kernel Claims Orchestration Package.

Provides mixed pattern orchestration (Sequential → Magentic → Handoff)
for insurance claims processing with native Semantic Kernel support.

Public API:
    - create_runtime: Bootstrap the complete runtime environment
    - ClaimsOrchestrator: Main orchestration engine
    - ClaimsMagenticManager: Custom termination policy manager
    - configure_telemetry: OpenTelemetry setup for Aspire Dashboard
"""

from .runtime import create_runtime, CoreRuntime
from .orchestration import ClaimsOrchestrator, build_orchestrator
from .managers import ClaimsMagenticManager
from .agents import AgentFactory, load_agent_config
from .observability import configure_telemetry, get_tracer, get_metrics

__version__ = "0.1.0"

__all__ = [
    "create_runtime",
    "CoreRuntime",
    "ClaimsOrchestrator",
    "build_orchestrator",
    "ClaimsMagenticManager",
    "AgentFactory",
    "load_agent_config",
    "configure_telemetry",
    "get_tracer",
    "get_metrics",
]
