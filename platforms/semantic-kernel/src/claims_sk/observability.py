"""
Observability module for Claims Orchestration with Aspire Dashboard integration.

Configures OpenTelemetry SDK with:
- OTLP gRPC exporters for traces and metrics
- Resource attributes (service.name, etc.)
- Logging instrumentation
- Span attributes for BPMN state tracking

Integrates with Aspire Dashboard for local development observability.
"""

import logging
import os
from typing import Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor

logger = logging.getLogger(__name__)


def configure_telemetry(
    endpoint: Optional[str] = None,
    service_name: str = "claims-orchestrator",
    enable_logging: bool = True,
) -> None:
    """
    Configure OpenTelemetry with OTLP exporters for Aspire Dashboard.
    
    Args:
        endpoint: OTLP gRPC endpoint (default: http://localhost:4317)
        service_name: Service identifier for Resource attributes
        enable_logging: Whether to instrument Python logging
    
    Environment Variables:
        - OTEL_EXPORTER_OTLP_ENDPOINT: Override endpoint
        - OTEL_EXPORTER_OTLP_PROTOCOL: Must be "grpc"
        - OTEL_SERVICE_NAME: Override service name
        - ASPIRE_ALLOW_UNSECURED_TRANSPORT: Set to "1" for local dev
    """
    # Use environment variables if available
    endpoint = endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    service_name = os.getenv("OTEL_SERVICE_NAME", service_name)
    
    # Ensure unsecured transport for local Aspire dashboard
    if "localhost" in endpoint or "127.0.0.1" in endpoint:
        os.environ["ASPIRE_ALLOW_UNSECURED_TRANSPORT"] = "1"
    
    logger.info(
        "Configuring telemetry: endpoint=%s, service_name=%s",
        endpoint,
        service_name,
    )
    
    # Create resource with service metadata
    resource = Resource.create({
        SERVICE_NAME: service_name,
        "service.version": "0.1.0",
        "deployment.environment": os.getenv("ENVIRONMENT", "development"),
    })
    
    # Configure tracing
    _configure_tracing(endpoint, resource)
    
    # Configure metrics
    _configure_metrics(endpoint, resource)
    
    # Configure logging instrumentation
    if enable_logging:
        _configure_logging()
    
    logger.info("Telemetry configuration complete")


def _configure_tracing(endpoint: str, resource: Resource) -> None:
    """
    Configure OpenTelemetry tracing with OTLP gRPC exporter.
    """
    # Create OTLP span exporter
    otlp_exporter = OTLPSpanExporter(
        endpoint=endpoint,
        insecure=True,  # Required for local Aspire dashboard
    )
    
    # Create tracer provider with batch processor
    tracer_provider = TracerProvider(resource=resource)
    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)
    
    # Set global tracer provider
    trace.set_tracer_provider(tracer_provider)
    
    logger.debug("Tracing configured with OTLP exporter: %s", endpoint)


def _configure_metrics(endpoint: str, resource: Resource) -> None:
    """
    Configure OpenTelemetry metrics with OTLP gRPC exporter.
    """
    # Create OTLP metric exporter
    otlp_exporter = OTLPMetricExporter(
        endpoint=endpoint,
        insecure=True,  # Required for local Aspire dashboard
    )
    
    # Create metric reader with periodic export
    metric_reader = PeriodicExportingMetricReader(
        exporter=otlp_exporter,
        export_interval_millis=5000,  # Export every 5 seconds
    )
    
    # Create meter provider
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )
    
    # Set global meter provider
    metrics.set_meter_provider(meter_provider)
    
    logger.debug("Metrics configured with OTLP exporter: %s", endpoint)


def _configure_logging() -> None:
    """
    Configure logging instrumentation to emit logs as OpenTelemetry events.
    """
    LoggingInstrumentor().instrument(set_logging_format=True)
    logger.debug("Logging instrumentation configured")


class ClaimsTracer:
    """
    Helper class for creating spans with BPMN-aligned attributes.
    
    Provides convenience methods for emitting span attributes that map
    to BPMN states and orchestration events.
    """
    
    def __init__(self, service_name: str = "claims-orchestrator"):
        """
        Initialize the claims tracer.
        
        Args:
            service_name: Service identifier for tracer
        """
        self.tracer = trace.get_tracer(service_name)
    
    def create_claim_span(
        self,
        operation_name: str,
        claim_id: Optional[str] = None,
        attributes: Optional[dict] = None,
    ):
        """
        Create a span for a claim operation with standard attributes.
        
        Args:
            operation_name: Name of the operation (e.g., "phase1_intake")
            claim_id: Claim identifier
            attributes: Additional span attributes
        
        Returns:
            OpenTelemetry span context manager
        """
        attrs = attributes or {}
        
        if claim_id:
            attrs["claim.id"] = claim_id
        
        return self.tracer.start_as_current_span(
            operation_name,
            attributes=attrs,
        )
    
    def set_bpmn_state(self, span, state: str) -> None:
        """
        Set BPMN state attribute on span.
        
        Args:
            span: OpenTelemetry span
            state: BPMN state name (e.g., "intake", "adaptive_gathering")
        """
        span.set_attribute("bpmn.state", state)
    
    def set_claim_event(self, span, event: str, value: Optional[str] = None) -> None:
        """
        Set claim event attribute on span.
        
        Args:
            span: OpenTelemetry span
            event: Event name (e.g., "ack_sent", "agent_decision_recorded")
            value: Optional event value
        """
        attr_name = f"claim.{event}"
        span.set_attribute(attr_name, value if value is not None else True)
    
    def record_orchestration_result(
        self,
        span,
        status: str,
        termination_reason: str,
        rounds: int,
    ) -> None:
        """
        Record final orchestration result on span.
        
        Args:
            span: OpenTelemetry span
            status: Orchestration status
            termination_reason: Why orchestration ended
            rounds: Number of rounds executed
        """
        span.set_attribute("orchestration.status", status)
        span.set_attribute("orchestration.termination_reason", termination_reason)
        span.set_attribute("orchestration.rounds", rounds)


class ClaimsMetrics:
    """
    Helper class for recording claims orchestration metrics.
    
    Provides convenience methods for emitting metrics aligned with
    claims processing KPIs.
    """
    
    def __init__(self, service_name: str = "claims-orchestrator"):
        """
        Initialize the claims metrics recorder.
        
        Args:
            service_name: Service identifier for meter
        """
        self.meter = metrics.get_meter(service_name)
        
        # Create standard metrics
        self.claims_processed = self.meter.create_counter(
            name="claims.processed",
            description="Total number of claims processed",
            unit="1",
        )
        
        self.claims_approved = self.meter.create_counter(
            name="claims.approved",
            description="Total number of claims approved",
            unit="1",
        )
        
        self.claims_denied = self.meter.create_counter(
            name="claims.denied",
            description="Total number of claims denied",
            unit="1",
        )
        
        self.orchestration_duration = self.meter.create_histogram(
            name="orchestration.duration",
            description="Duration of orchestration in seconds",
            unit="s",
        )
        
        self.orchestration_rounds = self.meter.create_histogram(
            name="orchestration.rounds",
            description="Number of orchestration rounds executed",
            unit="1",
        )
        
        self.risk_score = self.meter.create_histogram(
            name="claims.risk_score",
            description="Risk score distribution",
            unit="1",
        )
    
    def record_claim_processed(self, status: str, attributes: Optional[dict] = None) -> None:
        """
        Record a processed claim.
        
        Args:
            status: Orchestration status (approved, denied, etc.)
            attributes: Additional metric attributes
        """
        attrs = attributes or {}
        attrs["status"] = status
        
        self.claims_processed.add(1, attributes=attrs)
        
        if status == "approved":
            self.claims_approved.add(1, attributes=attrs)
        elif status == "denied":
            self.claims_denied.add(1, attributes=attrs)
    
    def record_orchestration_duration(self, duration_seconds: float, attributes: Optional[dict] = None) -> None:
        """
        Record orchestration duration.
        
        Args:
            duration_seconds: Duration in seconds
            attributes: Additional metric attributes
        """
        self.orchestration_duration.record(duration_seconds, attributes=attributes or {})
    
    def record_orchestration_rounds(self, rounds: int, attributes: Optional[dict] = None) -> None:
        """
        Record number of orchestration rounds.
        
        Args:
            rounds: Number of rounds executed
            attributes: Additional metric attributes
        """
        self.orchestration_rounds.record(rounds, attributes=attributes or {})
    
    def record_risk_score(self, score: int, attributes: Optional[dict] = None) -> None:
        """
        Record claim risk score.
        
        Args:
            score: Risk score (0-100)
            attributes: Additional metric attributes
        """
        self.risk_score.record(score, attributes=attributes or {})


# Global instances for convenience
_tracer: Optional[ClaimsTracer] = None
_metrics: Optional[ClaimsMetrics] = None


def get_tracer() -> ClaimsTracer:
    """
    Get the global ClaimsTracer instance.
    
    Returns:
        ClaimsTracer singleton
    """
    global _tracer
    if _tracer is None:
        _tracer = ClaimsTracer()
    return _tracer


def get_metrics() -> ClaimsMetrics:
    """
    Get the global ClaimsMetrics instance.
    
    Returns:
        ClaimsMetrics singleton
    """
    global _metrics
    if _metrics is None:
        _metrics = ClaimsMetrics()
    return _metrics
