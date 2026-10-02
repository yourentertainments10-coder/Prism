"""Prism-owned discovery metadata and separately loaded reviewed providers."""

import json
import os
from pathlib import Path

from prism_superagent.api_registry.models import CatalogEntry, ReviewedProvider


class APIRegistry:
    def __init__(self, catalog_path=None, provider_dir=None):
        package_dir = Path(__file__).resolve().parent
        self.catalog_path = Path(
            catalog_path or package_dir / "data" / "api_catalog.json"
        )
        self.provider_dir = Path(provider_dir or package_dir / "data" / "providers")
        self.catalog_document = self._load_catalog()
        self.entries = tuple(
            CatalogEntry.from_dict(item)
            for item in self.catalog_document.get("entries", [])
        )
        self.by_id = {entry.entry_id: entry for entry in self.entries}
        self.providers = self._load_providers()

    def _load_catalog(self):
        if not self.catalog_path.exists():
            return {
                "schema_version": 1,
                "source": {},
                "counts": {},
                "categories": [],
                "issues": [],
                "entries": [],
            }
        try:
            value = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not load Prism's API catalogue: {exc}") from None
        if value.get("schema_version") != 1 or not isinstance(
            value.get("entries"), list
        ):
            raise ValueError("Prism API catalogue has an unsupported schema.")
        return value

    def _load_providers(self):
        providers = {}
        if not self.provider_dir.exists():
            return providers
        for path in sorted(self.provider_dir.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            provider = ReviewedProvider.from_dict(value)
            if provider.provider_id in providers:
                raise ValueError(
                    f"Duplicate reviewed provider ID: {provider.provider_id}"
                )
            if not self.has_catalog_entry(
                provider.catalog_entry_name, provider.catalog_category
            ):
                raise ValueError(
                    f"Provider {provider.provider_id} is not linked to a discovered catalogue entry."
                )
            providers[provider.provider_id] = provider
        return providers

    def has_catalog_entry(self, name, category):
        return any(
            entry.name.casefold() == name.casefold()
            and entry.category.casefold() == category.casefold()
            for entry in self.entries
        )

    def candidates(self, capability, configured_only=True):
        values = [
            provider
            for provider in self.providers.values()
            if provider.enabled and provider.capability == capability
        ]
        if configured_only:
            values = [provider for provider in values if self.is_configured(provider)]
        return sorted(
            values, key=lambda provider: (provider.priority, provider.provider_id)
        )

    @staticmethod
    def is_configured(provider):
        import re

        required = set(provider.environment_variable_references)
        required.update(provider.header_environment.values())
        for template in provider.headers.values():
            required.update(re.findall(r"\{env:([A-Z][A-Z0-9_]*)\}", template))
        auth = provider.authentication_configuration
        if auth.get("type") in ("bearer", "header") and auth.get(
            "environment_variable"
        ):
            required.add(auth["environment_variable"])
        return all(os.environ.get(name) for name in required)
