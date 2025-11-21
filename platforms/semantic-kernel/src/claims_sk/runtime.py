"""Runtime bootstrap helpers for the Semantic Kernel backend."""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

from .agents import load_agent_config
from .orchestration import build_orchestrator

logger = logging.getLogger(__name__)


@dataclass
class AzureSettings:
    endpoint: str
    api_key: str
    deployment: str
    api_version: str = "2024-02-01"


@dataclass
class ObservabilitySettings:
    enabled: bool
    endpoint: Optional[str]
    service_name: str


@dataclass
class OrchestrationSettings:
    max_rounds: int = 15
    stall_threshold: int = 3
    enable_human_in_loop: bool = True


@dataclass
class RuntimeSettings:
    azure: AzureSettings
    observability: ObservabilitySettings
    orchestration: OrchestrationSettings


class CoreRuntime:
    """
    Bootstrap helper for Semantic Kernel claims orchestration runtime.
    
    Handles:
    - Environment configuration loading
    - Azure OpenAI service initialization
    - Kernel setup with plugins
    - Agent loading from configuration
    - Observability initialization
    
    Attributes:
        kernel: Configured Semantic Kernel instance
        config: Runtime configuration dictionary
        agents: Loaded specialist agents
        orchestrator: Ready-to-use ClaimsOrchestrator instance
    """
    
    def __init__(
        self,
        env_path: Optional[Path] = None,
        config_dir: Optional[Path] = None,
    ):
        """
        Initialize the CoreRuntime.
        
        Args:
            env_path: Path to .env file (default: workspace root)
            config_dir: Path to config directory (default: platforms/semantic-kernel/config/)
        """
        self.env_path = env_path or Path.cwd() / ".env"
        default_config_dir = Path(__file__).resolve().parents[2] / "config"
        self.config_dir = config_dir or default_config_dir
        
        self.kernel: Optional[Kernel] = None
        self.settings: Optional[RuntimeSettings] = None
        self.agents: Dict[str, Any] = {}
        self.orchestrator = None
        self.tool_plugins: Dict[str, object] = {}
        
        logger.info(
            "CoreRuntime initialized: env_path=%s, config_dir=%s",
            self.env_path,
            self.config_dir,
        )
    
    async def bootstrap(self) -> "CoreRuntime":
        """
        Bootstrap the complete runtime environment.
        
        Steps:
        1. Load environment variables
        2. Initialize Azure OpenAI kernel
        3. Register tool plugins
        4. Load agent configurations
        5. Initialize observability
        6. Build orchestrator
        
        Returns:
            Self (for chaining)
        """
        logger.info("Bootstrapping CoreRuntime...")
        
        # Step 1: Load environment
        self.settings = self._load_environment()
        
        # Step 2: Initialize kernel with Azure OpenAI
        self._initialize_kernel()
        
        # Step 3: Register tool plugins
        await self._register_plugins()
        
        # Step 4: Load agent configurations
        self._load_agents()
        
        # Step 5: Initialize observability (if enabled)
        self._initialize_observability()
        
        # Step 6: Build orchestrator
        self.orchestrator = await build_orchestrator(
            kernel=self.kernel,
            agents=self.agents,
            config=self._orchestration_dict,
        )
        
        logger.info("CoreRuntime bootstrap complete")
        return self
    
    def _load_environment(self) -> RuntimeSettings:
        """
        Load environment variables from .env file.
        
        Required variables:
        - AZURE_OPENAI_ENDPOINT
        - AZURE_OPENAI_API_KEY
        - AZURE_OPENAI_DEPLOYMENT
        - AZURE_OPENAI_API_VERSION (optional, defaults to "2024-02-01")
        
        Optional variables:
        - OTEL_EXPORTER_OTLP_ENDPOINT
        - OTEL_SERVICE_NAME
        - LOG_LEVEL
        """
        if self.env_path.exists():
            load_dotenv(self.env_path)
            logger.info("Loaded environment from: %s", self.env_path)
        else:
            logger.warning("No .env file found at: %s", self.env_path)
        
        # Validate required Azure OpenAI settings
        required_vars = [
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_DEPLOYMENT",
        ]
        
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {missing}")
        
        settings = RuntimeSettings(
            azure=AzureSettings(
                endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            ),
            observability=ObservabilitySettings(
                enabled=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") is not None,
                endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
                service_name=os.getenv("OTEL_SERVICE_NAME", "claims-orchestrator"),
            ),
            orchestration=OrchestrationSettings(
                max_rounds=int(os.getenv("ORCHESTRATION_MAX_ROUNDS", "15")),
                stall_threshold=int(os.getenv("ORCHESTRATION_STALL_THRESHOLD", "3")),
                enable_human_in_loop=os.getenv("ORCHESTRATION_ENABLE_HITL", "true").lower() == "true",
            ),
        )
        
        # Configure logging
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        logging.basicConfig(
            level=getattr(logging, log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        
        logger.info("Environment configuration loaded")
        return settings
    
    def _initialize_kernel(self) -> None:
        """
        Initialize Semantic Kernel with Azure OpenAI service.
        """
        self.kernel = Kernel()
        
        azure_config = self.settings.azure
        chat_service = AzureChatCompletion(
            service_id="default",
            deployment_name=azure_config.deployment,
            endpoint=azure_config.endpoint,
            api_key=azure_config.api_key,
            api_version=azure_config.api_version,
        )
        
        self.kernel.add_service(chat_service)
        
        logger.info(
            "Kernel initialized with Azure OpenAI: deployment=%s, endpoint=%s",
            azure_config.deployment,
            azure_config.endpoint,
        )
    
    async def _register_plugins(self) -> None:
        """
        Register tool plugins with the kernel.
        
        Loads plugins from claims_sk/tools/:
        - Policy lookup tools
        - Fraud detection tools
        - Claims history tools
        - Vendor verification tools
        - Document validation tools
        - Handoff payload tools
        """
        try:
            from .tools import register_tool_plugins
        except ImportError as exc:  # pragma: no cover - defensive
            logger.error("Unable to import tool registration helper: %s", exc)
            return

        if not self.kernel:
            raise RuntimeError("Kernel must be initialized before registering plugins")

        try:
            self.tool_plugins = register_tool_plugins(self.kernel)
            logger.info("Registered %d tool plugins", len(self.tool_plugins))
        except Exception as exc:
            logger.error("Failed to register tool plugins: %s", exc)
    
    def _load_agents(self) -> None:
        """
        Load agent configurations from agents_config.yaml.
        """
        agents_config_path = self.config_dir / "agents_config.yaml"
        
        if not agents_config_path.exists():
            logger.warning("Agent config not found: %s", agents_config_path)
            # Generate default config for scaffolding
            from .agents import generate_default_config
            agents_config_path.parent.mkdir(parents=True, exist_ok=True)
            generate_default_config(agents_config_path)
            logger.info("Generated default agent config: %s", agents_config_path)
        
        self.agents = load_agent_config(agents_config_path, self.kernel)
        
        logger.info("Loaded %d agents from config", len(self.agents))
    
    def _initialize_observability(self) -> None:
        """
        Initialize OpenTelemetry observability if enabled.
        
        Delegates to observability.py module for OTLP exporter setup.
        """
        if not self.settings.observability.enabled:
            logger.info("Observability disabled (no OTEL_EXPORTER_OTLP_ENDPOINT)")
            return
        
        try:
            from .observability import configure_telemetry
            
            configure_telemetry(
                endpoint=self.settings.observability.endpoint,
                service_name=self.settings.observability.service_name,
            )
            
            logger.info(
                "Observability initialized: endpoint=%s, service=%s",
                self.settings.observability.endpoint,
                self.settings.observability.service_name,
            )
        except ImportError:
            logger.warning("Observability module not available, skipping telemetry setup")
        except Exception as e:
            logger.error("Failed to initialize observability: %s", str(e))
    
    def get_orchestrator(self):
        """
        Get the bootstrapped orchestrator instance.
        
        Returns:
            ClaimsOrchestrator ready to process claims
        
        Raises:
            RuntimeError: If bootstrap() hasn't been called
        """
        if not self.orchestrator:
            raise RuntimeError("Runtime not bootstrapped. Call bootstrap() first.")
        
        return self.orchestrator

    @property
    def _orchestration_dict(self) -> Dict[str, Any]:
        if not self.settings:
            return {}
        config = self.settings.orchestration
        return {
            "max_rounds": config.max_rounds,
            "stall_threshold": config.stall_threshold,
            "enable_human_in_loop": config.enable_human_in_loop,
        }


async def create_runtime(
    env_path: Optional[Path] = None,
    config_dir: Optional[Path] = None,
):
    """
    Convenience function to create and bootstrap runtime.
    
    Args:
        env_path: Path to .env file
        config_dir: Path to config directory
    
    Returns:
        Bootstrapped CoreRuntime instance
    """
    runtime = CoreRuntime(env_path=env_path, config_dir=config_dir)
    await runtime.bootstrap()
    return runtime
