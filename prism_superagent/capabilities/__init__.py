"""Unified capability and provider/model metadata for the active Prism app."""

from prism_superagent.capabilities.registry import (
    Capability,
    CapabilityRegistry,
    ProviderModel,
    build_capability_registry,
)

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "ProviderModel",
    "build_capability_registry",
]
