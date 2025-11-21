"""Shared Azure OpenAI helpers for the claims data generators."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Literal, TYPE_CHECKING

try:  # pragma: no cover - import guard mirrors individual scripts
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    AZURE_AVAILABLE = True
except Exception:  # pragma: no cover - only hit when deps missing
    AZURE_AVAILABLE = False
    if TYPE_CHECKING:  # pragma: no cover - typing aid only
        from openai import AzureOpenAI  # type: ignore[misc]
    else:
        AzureOpenAI = object  # type: ignore[assignment]

ReasoningEffort = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class LLMSettings:
    deployment: str
    use_reasoning: bool
    reasoning_effort: ReasoningEffort
    max_output_tokens: int
    temperature: float | None


def build_azure_client() -> AzureOpenAI:
    """Instantiate AzureOpenAI with Entra auth or raise when unavailable."""

    if not AZURE_AVAILABLE or AzureOpenAI is object:  # type: ignore[comparison-overlap]
        raise RuntimeError(
            "Azure OpenAI SDK with azure-identity is required. Install dependencies and configure credentials."
        )

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

    if not endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT must be set")

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )

    return AzureOpenAI(
        api_version=api_version,
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        timeout=300.0,  # 5 minutes timeout for large generation requests
        max_retries=2,
    )


def _truthy(value: str | None) -> bool:
    return bool(value) and value.lower() in {"1", "true", "yes", "on"}


def _parse_reasoning_effort() -> ReasoningEffort:
    value = os.getenv("AZURE_OPENAI_REASONING_EFFORT", "medium").lower()
    if value not in {"low", "medium", "high"}:
        raise RuntimeError("AZURE_OPENAI_REASONING_EFFORT must be one of: low, medium, high")
    return value  # type: ignore[return-value]


def _parse_max_tokens() -> int:
    raw = os.getenv("AZURE_OPENAI_MAX_OUTPUT_TOKENS", "4096")
    try:
        value = int(raw)
    except ValueError as exc:  # pragma: no cover - config error surfaced to user
        raise RuntimeError("AZURE_OPENAI_MAX_OUTPUT_TOKENS must be an integer") from exc
    if value <= 0:
        raise RuntimeError("AZURE_OPENAI_MAX_OUTPUT_TOKENS must be positive")
    return value


def _resolve_temperature(default: float | None) -> float | None:
    override = os.getenv("AZURE_OPENAI_TEMPERATURE")
    if override is None:
        return default
    try:
        return float(override)
    except ValueError as exc:  # pragma: no cover
        raise RuntimeError("AZURE_OPENAI_TEMPERATURE must be numeric") from exc


def _load_settings(
    default_temperature: float | None,
    *,
    deployment_override: str | None = None,
    reasoning_deployment_override: str | None = None,
    use_reasoning_override: bool | None = None,
) -> LLMSettings:
    base_deployment = deployment_override or os.getenv("AZURE_OPENAI_DEPLOYMENT")
    reasoning_deployment = reasoning_deployment_override or os.getenv("AZURE_OPENAI_REASONING_DEPLOYMENT")
    if use_reasoning_override is None:
        use_reasoning = _truthy(os.getenv("AZURE_OPENAI_USE_REASONING"))
    else:
        use_reasoning = use_reasoning_override

    if use_reasoning:
        deployment = reasoning_deployment or base_deployment
        if not deployment:
            raise RuntimeError(
                "Reasoning mode requested but no deployment configured. Set AZURE_OPENAI_REASONING_DEPLOYMENT or AZURE_OPENAI_DEPLOYMENT."
            )
        return LLMSettings(
            deployment=deployment,
            use_reasoning=True,
            reasoning_effort=_parse_reasoning_effort(),
            max_output_tokens=_parse_max_tokens(),
            temperature=None,
        )

    if not base_deployment:
        raise RuntimeError("AZURE_OPENAI_DEPLOYMENT must be set when reasoning is disabled")

    return LLMSettings(
        deployment=base_deployment,
        use_reasoning=False,
        reasoning_effort="medium",
        max_output_tokens=_parse_max_tokens(),
        temperature=_resolve_temperature(default_temperature),
    )


def build_response_kwargs(
    *,
    messages: list[dict[str, Any]],
    schema: Dict[str, Any],
    seed: int,
    temperature_default: float | None,
    deployment_override: str | None = None,
    reasoning_deployment_override: str | None = None,
    use_reasoning_override: bool | None = None,
) -> Dict[str, Any]:
    """Construct the kwargs for client.chat.completions.create with structured outputs.
    
    Supports both reasoning models (GPT-5.1) and non-reasoning models (GPT-4.1).
    Uses Chat Completions API which is faster than Responses API.
    """

    settings = _load_settings(
        temperature_default,
        deployment_override=deployment_override,
        reasoning_deployment_override=reasoning_deployment_override,
        use_reasoning_override=use_reasoning_override,
    )
    schema_name = schema.get("title") if isinstance(schema, dict) else None
    
    kwargs: Dict[str, Any] = {
        "model": settings.deployment,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name or "structured_response",
                "schema": schema,
                "strict": True
            }
        },
    }

    if settings.use_reasoning:
        # GPT-5.1 reasoning model parameters
        kwargs["reasoning_effort"] = settings.reasoning_effort
        kwargs["max_completion_tokens"] = settings.max_output_tokens
    else:
        # GPT-4.1 non-reasoning model parameters
        kwargs["max_completion_tokens"] = settings.max_output_tokens
        if settings.temperature is not None:
            kwargs["temperature"] = settings.temperature

    return kwargs


def extract_response_text(response: Any) -> str:
    """Extract the text content from a Chat Completions API response.
    
    Works with structured outputs from both reasoning and non-reasoning models.
    """
    if not hasattr(response, 'choices') or not response.choices:
        raise ValueError(f"Invalid response structure: {response}")
    
    choice = response.choices[0]
    if hasattr(choice, 'message') and hasattr(choice.message, 'content'):
        return choice.message.content
    
    raise ValueError(f"Could not extract text from response: {response}")


def fix_schema_for_azure(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Add additionalProperties: false to all object types in schema.
    
    Azure OpenAI API (2025-03-01-preview+) requires explicit 
    additionalProperties: false for structured outputs.
    """
    if isinstance(schema, dict):
        # Fix current level if it's an object type
        if schema.get("type") == "object" and "additionalProperties" not in schema:
            schema["additionalProperties"] = False
        
        # Recursively fix nested schemas
        for key, value in schema.items():
            if isinstance(value, dict):
                fix_schema_for_azure(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        fix_schema_for_azure(item)
    
    return schema


__all__ = [
    "AzureOpenAI",
    "build_azure_client",
    "build_response_kwargs",
    "extract_response_text",
    "fix_schema_for_azure",
]
