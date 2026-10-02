"""Common metadata for Prism's existing executors and model providers.

The registry describes implementations owned by their existing subsystems. It
does not copy, replace, or invoke those implementations.
"""

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Capability:
    capability_id: str
    name: str
    description: str
    input_requirements: dict[str, Any]
    executor: str
    availability: str
    verification_method: str
    requires_model: bool
    requires_network: bool
    cost_class: str
    priority: int
    source: str


@dataclass(frozen=True)
class ProviderModel:
    model_id: str
    provider: str
    classification: str
    availability: str
    capabilities: tuple[str, ...] = ()
    discovered_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CapabilityRegistry:
    """In-memory, deterministic inventory of capabilities and model records."""

    def __init__(self):
        self._capabilities = {}
        self._models = {}

    def register(self, capability: Capability):
        if not capability.capability_id:
            raise ValueError("Capability ID must not be empty.")
        existing = self._capabilities.get(capability.capability_id)
        if existing is not None and existing != capability:
            raise ValueError(
                f"Conflicting capability registration: {capability.capability_id}"
            )
        self._capabilities[capability.capability_id] = capability
        return capability

    def register_model(self, model: ProviderModel):
        if not model.model_id or not model.provider:
            raise ValueError("Model ID and provider are required.")
        self._models[(model.provider, model.model_id)] = model
        return model

    def get(self, capability_id):
        return self._capabilities.get(capability_id)

    def capabilities(self, *, executor=None):
        values = self._capabilities.values()
        if executor is not None:
            values = (item for item in values if item.executor == executor)
        return tuple(
            sorted(values, key=lambda item: (item.priority, item.capability_id))
        )

    def models(self, *, provider=None, classification=None):
        values = self._models.values()
        if provider is not None:
            values = (item for item in values if item.provider == provider)
        if classification is not None:
            values = (item for item in values if item.classification == classification)
        return tuple(sorted(values, key=lambda item: (item.provider, item.model_id)))


def build_capability_registry(
    deterministic_engine,
    api_registry,
    *,
    agent_tools=(),
    cloud_models=(),
    local_models=(),
):
    registry = CapabilityRegistry()
    planner = deterministic_engine.planner
    network_tasks = {"web_api_get", "web_search", "source_verify"}
    for task_kind, operations in planner.OPERATIONS.items():
        registry.register(
            Capability(
                capability_id=f"deterministic:{task_kind}",
                name=task_kind.replace("_", " ").title(),
                description=f"Run Prism's existing {task_kind} task graph.",
                input_requirements={"task_kind": task_kind},
                executor="deterministic_engine",
                availability="available",
                verification_method="ResultVerifier.verify",
                requires_model=False,
                requires_network=task_kind in network_tasks,
                cost_class="local_compute",
                priority=10,
                source=", ".join(operations),
            )
        )

    providers_by_capability = {}
    for provider in api_registry.providers.values():
        providers_by_capability.setdefault(provider.capability, []).append(provider)
    for name, providers in providers_by_capability.items():
        configured = [api_registry.is_configured(provider) for provider in providers]
        provider_names = tuple(sorted(item.provider_id for item in providers))
        registry.register(
            Capability(
                capability_id=f"api:{name}",
                name=name.replace("_", " ").title(),
                description=f"Call reviewed provider(s) for {name.replace('_', ' ')}.",
                input_requirements={
                    "providers": provider_names,
                    "required": tuple(
                        sorted(
                            {
                                parameter
                                for item in providers
                                for parameter in item.required_parameters
                            }
                        )
                    ),
                },
                executor="api_registry",
                availability=(
                    "configured" if any(configured) else "configuration_required"
                ),
                verification_method="API response schema validation",
                requires_model=False,
                requires_network=True,
                cost_class="unknown",
                priority=min(item.priority for item in providers),
                source=", ".join(provider_names),
            )
        )

    for tool in agent_tools:
        name = tool["function"]["name"]
        function = tool["function"]
        networked = name in {"web_search", "fetch_url", "generate_image"}
        requires_model = name == "generate_image"
        registry.register(
            Capability(
                capability_id=f"agent_tool:{name}",
                name=name.replace("_", " ").title(),
                description=function.get("description", "Existing Prism agent tool."),
                input_requirements=function.get("parameters", {}),
                executor="agent_tool",
                availability="agent_mode",
                verification_method="Tool result/error boundary",
                requires_model=requires_model,
                requires_network=networked,
                cost_class="unknown" if networked else "local_compute",
                priority=60,
                source="agent.tools.TOOL_IMPL",
            )
        )

    for item in cloud_models:
        key_name = {
            "anthropic": "ANTHROPIC_API_KEY",
            "nvidia": "NVIDIA_API_KEY",
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }.get(item["provider"])
        registry.register_model(
            ProviderModel(
                model_id=item["id"],
                provider=item["provider"],
                classification="cloud",
                availability=(
                    "configured"
                    if key_name and os.getenv(key_name)
                    else "configuration_required"
                ),
                capabilities=(),
                metadata={"name": item.get("name", item["id"])},
            )
        )

    for model in local_models:
        registry.register_model(
            ProviderModel(
                model_id=model.name,
                provider="ollama",
                classification=model.classification,
                availability=("available" if model.available else "unavailable"),
                capabilities=model.capabilities,
                discovered_at=model.discovered_at,
                metadata={
                    "confirmed_local": model.confirmed_local,
                    "size": model.size,
                    "context_length": model.context_length,
                    "remote_host": model.remote_host,
                },
            )
        )
        if model.confirmed_local and "completion" in model.capabilities:
            registry.register(
                Capability(
                    capability_id=f"local_model:{model.name}:document_summarization",
                    name=f"Document summarization ({model.name})",
                    description="Summarize extracted document text using a confirmed local model.",
                    input_requirements={"document_text": "non-empty extracted text"},
                    executor="ollama_local_model",
                    availability="available",
                    verification_method="Non-empty bounded output; semantic accuracy not independently verified",
                    requires_model=True,
                    requires_network=False,
                    cost_class="local_compute",
                    priority=40,
                    source="Ollama local model registry",
                )
            )
    return registry
