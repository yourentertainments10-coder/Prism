"""Match, execute, validate, cache, and fail over across reviewed providers."""

import json
import os
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from prism_superagent.api_registry.cache import APIResponseCache
from prism_superagent.api_registry.errors import (
    APIProvidersUnavailable,
    APIRequestError,
    ProviderConfigurationError,
)
from prism_superagent.api_registry.executor import SafeAPIExecutor
from prism_superagent.api_registry.health import ProviderHealthMonitor
from prism_superagent.api_registry.matcher import RegistryMatcher
from prism_superagent.api_registry.models import ProviderMatch
from prism_superagent.api_registry.registry import APIRegistry
from prism_superagent.tracing import record_trace


class APIRegistryRuntime:
    def __init__(
        self, registry=None, matcher=None, executor=None, cache=None, health=None
    ):
        self.registry = registry or APIRegistry()
        self.matcher = matcher or RegistryMatcher()
        self.executor = executor or SafeAPIExecutor()
        self.cache = cache or APIResponseCache()
        self.health = health or ProviderHealthMonitor()
        self._throttle_times = {}
        self._throttle_lock = threading.RLock()

    def match(self, request):
        value = self.matcher.match(request, self.registry)
        if value is None:
            return None
        return ProviderMatch(**value)

    def execute(self, matched: ProviderMatch):
        failures = []
        providers = [
            self.registry.providers[item]
            for item in matched.provider_ids
            if item in self.registry.providers
        ]
        providers = self._order_for_health(providers)
        for provider in providers:
            if not self.registry.is_configured(provider):
                failures.append(
                    (provider.provider_id, "required configuration is missing")
                )
                continue
            request_parameters = dict(provider.default_parameters)
            request_parameters.update(
                {
                    key: value
                    for key, value in matched.parameters.items()
                    if key in provider.query_parameters
                    or key in provider.path_parameters
                }
            )
            cache_params = {key: value for key, value in request_parameters.items()}
            credential_scope = _credential_values(provider)
            cache_key = self.cache.key(
                provider.provider_id, cache_params, credential_scope
            )
            cached = self.cache.get(cache_key)
            if cached is not None:
                return replace(
                    cached,
                    cache_hit=True,
                    confidence=matched.confidence,
                    match_explanation=matched.explanation,
                    requested_amount=matched.parameters.get("amount"),
                )

            self._throttle(provider)
            try:
                record_trace(
                    "external_api_request",
                    provider_id=provider.provider_id,
                    capability=provider.capability,
                )
                response, latency_ms, validation = self.executor.execute(
                    provider, request_parameters
                )
            except (APIRequestError, ProviderConfigurationError) as exc:
                now = datetime.now(timezone.utc).isoformat()
                self.health.record_failure(
                    provider.provider_id,
                    getattr(exc, "status_code", None),
                    _exception_latency(exc),
                    now,
                    str(exc),
                    reachable=getattr(exc, "reachable", None),
                    response_valid=getattr(exc, "response_valid", False),
                    schema_valid=getattr(exc, "schema_valid", False),
                )
                failures.append((provider.provider_id, str(exc)))
                continue
            response = replace(
                response,
                confidence=matched.confidence,
                match_explanation=matched.explanation,
                requested_amount=matched.parameters.get("amount"),
            )
            self.health.record_success(
                provider.provider_id,
                response.status,
                latency_ms,
                response.retrieved_at,
                validation["response_valid"],
                validation["schema_valid"],
            )
            ttl = int(provider.cache_policy.get("ttl_seconds", 0))
            self.cache.put(
                cache_key, replace(response, requested_amount=None), ttl, success=True
            )
            return response
        raise APIProvidersUnavailable(matched.capability, failures)

    def _order_for_health(self, providers):
        # Prefer providers without a recent failure, but retain declared priority
        # within each group. A provider gets a short cooldown, then is retried.
        now = time.time()
        return sorted(
            providers,
            key=lambda provider: (
                self._in_cooldown(provider.provider_id, now),
                provider.priority,
                provider.provider_id,
            ),
        )

    def _in_cooldown(self, provider_id, now):
        state = self.health.get(provider_id)
        failed = state.get("last_failure_at")
        if not failed:
            return False
        try:
            stamp = datetime.fromisoformat(failed).timestamp()
        except (ValueError, TypeError):
            return False
        return now - stamp < 30

    def _throttle(self, provider):
        interval = provider.min_interval_seconds
        if not interval:
            return
        with self._throttle_lock:
            now = time.monotonic()
            wait = interval - (now - self._throttle_times.get(provider.provider_id, 0))
            if wait > 0:
                time.sleep(wait)
            self._throttle_times[provider.provider_id] = time.monotonic()

    def health_snapshot(self):
        return self.health.snapshot()


def format_response(response):
    """Render useful compact output without making authority/truth claims."""
    data = response.data
    if response.capability == "geocoding" and isinstance(data, dict):
        results = data.get("results") or []
        if not results:
            return "No matching location was returned by the configured geocoder."
        lines = []
        for item in results[:5]:
            place = ", ".join(
                str(item[key]) for key in ("name", "admin1", "country") if item.get(key)
            )
            lines.append(f"- {place}: {item.get('latitude')}, {item.get('longitude')}")
        return "Location matches:\n" + "\n".join(lines)
    if response.capability == "currency_rate" and isinstance(data, dict):
        rate = data.get("rate")
        base, quote_code = data.get("base", ""), data.get("quote", "")
        date = data.get("date", "")
        amount = getattr(response, "requested_amount", None)
        if amount is not None:
            try:
                converted = Decimal(str(amount)) * Decimal(str(rate))
                return f"{amount} {base} = {converted.normalize()} {quote_code} (rate date: {date})."
            except (InvalidOperation, TypeError):
                pass
        return f"1 {base} = {rate} {quote_code} (rate date: {date})."
    if response.capability == "book_search" and isinstance(data, dict):
        docs = data.get("docs", [])
        if not docs:
            return "No matching books were returned by the configured book catalogue."
        lines = []
        for book in docs[:8]:
            title = book.get("title", "(untitled)")
            authors = ", ".join(book.get("author_name", [])[:3])
            year = book.get("first_publish_year")
            details = " — ".join(
                item for item in (authors, str(year) if year else "") if item
            )
            lines.append(f"- {title}" + (f" ({details})" if details else ""))
        return "Book search results:\n" + "\n".join(lines)
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)[:12_000]


def _credential_values(provider):
    names = set(provider.environment_variable_references)
    names.update(provider.header_environment.values())
    for template in provider.headers.values():
        import re

        names.update(re.findall(r"\{env:([A-Z][A-Z0-9_]*)\}", template))
    auth = provider.authentication_configuration
    if auth.get("environment_variable"):
        names.add(auth["environment_variable"])
    return tuple(
        sorted(os.environ.get(name, "") for name in names if os.environ.get(name))
    )


def _exception_latency(exc):
    return getattr(exc, "latency_ms", None)
