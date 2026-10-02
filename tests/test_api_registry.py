import json
import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from prism_superagent.api_registry.cache import APIResponseCache
from prism_superagent.api_registry.catalog import (
    normalize_auth,
    normalize_yes_no,
    parse_catalog,
)
from prism_superagent.api_registry.discovery import import_catalogue
from prism_superagent.api_registry.errors import (
    APIRequestError,
    ProviderConfigurationError,
)
from prism_superagent.api_registry.executor import SafeAPIExecutor
from prism_superagent.api_registry.health import ProviderHealthMonitor
from prism_superagent.api_registry.integration import (
    classify_chat_routes,
    select_chat_provider,
)
from prism_superagent.api_registry.matcher import RegistryMatcher
from prism_superagent.api_registry.models import APIResponse, ReviewedProvider
from prism_superagent.api_registry.registry import APIRegistry
from prism_superagent.api_registry.runtime import APIRegistryRuntime
from prism_superagent.api_registry.validator import (
    ResponseValidationError,
    ResponseValidator,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_REPO = ROOT / "public-apis"
EXPECTED_COMMIT = "da95f28e9eeb9cb2e5498b0636d25570ca9831e5"


def provider(**overrides):
    record = {
        "provider_id": "test_provider",
        "name": "Test",
        "capability": "geocoding",
        "base_url": "https://api.example.test",
        "allowed_hosts": ["api.example.test"],
        "endpoint": "/v1/search",
        "method": "GET",
        "query_parameters": {"name": {"type": "string", "max_length": 100}},
        "required_parameters": ["name"],
        "default_parameters": {},
        "response_type": "json",
        "response_schema": {"type": "object", "required": ["results"]},
        "authentication_configuration": {"type": "none"},
        "environment_variable_references": [],
        "timeout_seconds": 3,
        "response_size_limit": 2048,
        "cache_policy": {"ttl_seconds": 60},
        "pricing_status": "unknown",
        "authority_status": "not_assessed",
        "verification_status": "not_live_checked",
        "catalog_entry_name": "Test",
        "catalog_category": "Science",
        "headers": {},
        "header_environment": {},
        "path_parameters": [],
        "priority": 10,
        "enabled": True,
    }
    record.update(overrides)
    return ReviewedProvider.from_dict(record)


def public_resolver(host, port, type):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]


def test_imports_local_catalogue_revision_count_and_discovered_state(tmp_path):
    output = tmp_path / "api_catalog.json"
    result = import_catalogue(CATALOGUE_REPO, output)
    assert result["counts"] == {"entries": 1966, "categories": 51, "parse_issues": 1}
    assert result["source"]["commit"] == EXPECTED_COMMIT
    assert result["source"]["readme_sha256"] and output.is_file()
    first = result["entries"][0]
    assert first["status"] == "discovered"
    assert first["health"] == "unknown" and first["endpoint_verified"] is False
    assert first["source_commit"] == EXPECTED_COMMIT


def test_parser_excludes_other_tables_and_preserves_duplicate_names():
    fixture = (ROOT / "tests/fixtures/public_apis_sample.md").read_text(
        encoding="utf-8"
    )
    result = parse_catalog(
        fixture, "fixture-commit", imported_at="2026-10-02T00:00:00+00:00"
    )
    assert [entry.name for entry in result.entries] == [
        "Same Name",
        "Same Name",
        "Recoverable",
        "Same Name",
    ]
    assert [entry.category for entry in result.entries] == [
        "Books",
        "Books",
        "Books",
        "Science",
    ]
    assert len({entry.entry_id for entry in result.entries}) == 4


def test_parser_reports_malformed_row_and_preserves_extra_cells():
    fixture = (ROOT / "tests/fixtures/public_apis_sample.md").read_text(
        encoding="utf-8"
    )
    result = parse_catalog(fixture, "fixture-commit")
    extra = next(entry for entry in result.entries if entry.name == "Recoverable")
    assert extra.raw_extra_cells == ("source note",)
    assert len(result.issues) == 2
    assert any("extra cells preserved" in issue["reason"] for issue in result.issues)
    assert any("expected 5 cells" in issue["reason"] for issue in result.issues)


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("No", "none"),
        ("`No`", "none"),
        ("apiKey", "api_key"),
        ("`OAuth`", "oauth"),
        ("X-Mashape-Key", "other"),
        ("Unknown", "unknown"),
    ],
)
def test_auth_normalization(raw, normalized):
    assert normalize_auth(raw) == normalized


def test_yes_no_normalization_is_tristate():
    assert normalize_yes_no("Yes") is True
    assert normalize_yes_no("No") is False
    assert normalize_yes_no("Unknown") is None
    assert normalize_yes_no("`Yes`") is True


def test_registry_loads_only_explicit_provider_configs(monkeypatch):
    monkeypatch.setenv("PRISM_API_CONTACT", "test@example.invalid")
    registry = APIRegistry()
    assert len(registry.entries) == 1966
    assert set(registry.providers) == {
        "open_meteo_geocoding",
        "frankfurter_currency_rate",
        "open_library_book_search",
    }
    assert all(item.method == "GET" for item in registry.providers.values())


def test_matcher_extracts_slots_and_rejects_unsupported_intents(monkeypatch):
    monkeypatch.setenv("PRISM_API_CONTACT", "test@example.invalid")
    registry = APIRegistry()
    matcher = RegistryMatcher()
    assert matcher.match("Find coordinates for Delhi", registry)["parameters"] == {
        "name": "Delhi"
    }
    fx = matcher.match("Convert 250 USD to INR", registry)
    assert fx["capability"] == "currency_rate"
    assert fx["parameters"] == {"base": "USD", "quote": "INR", "amount": "250"}
    books = matcher.match("Search books about Ada Lovelace", registry)
    assert books["capability"] == "book_search" and books["parameters"] == {
        "q": "Ada Lovelace"
    }
    assert matcher.match("Explain why my application is slow", registry) is None


def test_executor_uses_fixed_host_and_allowlisted_query_parameters():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200, json={"results": [{"name": "Delhi"}]}, request=request
        )

    executor = SafeAPIExecutor(
        transport=httpx.MockTransport(handler), resolver=public_resolver
    )
    result, latency, validation = executor.execute(provider(), {"name": "Delhi"})
    assert result.status == 200 and result.data == {"results": [{"name": "Delhi"}]}
    assert len(result.sha256) == 64 and latency >= 0
    assert validation == {"response_valid": True, "schema_valid": True}
    assert str(seen[0].url) == "https://api.example.test/v1/search?name=Delhi"


def test_executor_blocks_private_resolution_before_request():
    called = []

    def handler(request):
        called.append(request)
        return httpx.Response(200, json={"results": []}, request=request)

    def private_resolver(host, port, type):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    executor = SafeAPIExecutor(
        transport=httpx.MockTransport(handler), resolver=private_resolver
    )
    with pytest.raises(ProviderConfigurationError, match="private or non-public"):
        executor.execute(provider(), {"name": "x"})
    assert called == []


def test_executor_enforces_host_and_parameter_allowlists():
    executor = SafeAPIExecutor(
        transport=httpx.MockTransport(lambda request: None), resolver=public_resolver
    )
    with pytest.raises(ProviderConfigurationError, match="not in its allowed_hosts"):
        executor.execute(provider(allowed_hosts=["other.example.test"]), {"name": "x"})
    with pytest.raises(
        APIRequestError, match="parameters that this provider does not allow"
    ):
        executor.execute(provider(), {"name": "x", "url": "https://attacker.test"})


def test_executor_refuses_redirect_without_following_it():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            302, headers={"Location": "https://other.example.test/"}, request=request
        )

    executor = SafeAPIExecutor(
        transport=httpx.MockTransport(handler), resolver=public_resolver
    )
    with pytest.raises(APIRequestError, match="redirect refused"):
        executor.execute(provider(), {"name": "Delhi"})
    assert len(seen) == 1


def test_response_validation_checks_required_values_and_types():
    validator = ResponseValidator()
    schema = {
        "type": "object",
        "required": ["results"],
        "properties": {"results": {"type": "array"}},
    }
    assert validator.validate({"results": []}, "json", schema)["schema_valid"]
    with pytest.raises(ResponseValidationError, match="missing required"):
        validator.validate({}, "json", schema)
    with pytest.raises(ResponseValidationError, match="JSON type array"):
        validator.validate({"results": "bad"}, "json", schema)


def test_response_cache_is_bounded_success_only_and_secrets_are_hashed():
    cache = APIResponseCache(max_entries=1, max_bytes=2048)
    key = cache.key("provider", {"q": "x"}, ("secret-one",))
    assert "secret-one" not in key
    assert key != cache.key("provider", {"q": "x"}, ("secret-two",))
    assert not cache.put(key, {"bad": True}, 60, success=False)
    assert cache.get(key) is None
    assert cache.put(key, {"ok": True}, 60, success=True)
    assert cache.get(key) == {"ok": True}
    cache.put("second", {"ok": 2}, 60)
    assert len(cache) == 1 and cache.get(key) is None


def test_response_cache_expires_after_provider_ttl(monkeypatch):
    import prism_superagent.api_registry.cache as cache_module

    now = [100.0]
    monkeypatch.setattr(cache_module.time, "monotonic", lambda: now[0])
    cache = APIResponseCache()
    cache.put("key", {"value": 1}, 5)
    now[0] = 104.9
    assert cache.get("key") == {"value": 1}
    now[0] = 105.0
    assert cache.get("key") is None


def test_health_monitor_tracks_success_and_failure_separately():
    health = ProviderHealthMonitor()
    health.record_success("p", 200, 12.345, "2026-10-02T00:00:00+00:00")
    health.record_failure(
        "p",
        503,
        20,
        "2026-10-02T00:01:00+00:00",
        "unavailable",
        reachable=True,
        response_valid=False,
        schema_valid=False,
    )
    state = health.get("p")
    assert state["http_status"] == 503 and state["latency_ms"] == 20
    assert state["last_success_at"] == "2026-10-02T00:00:00+00:00"
    assert state["last_failure_at"] == "2026-10-02T00:01:00+00:00"
    assert state["response_valid"] is False and state["schema_valid"] is False


def test_contact_gated_provider_is_not_matched_until_configured(monkeypatch):
    monkeypatch.delenv("PRISM_API_CONTACT", raising=False)
    registry = APIRegistry()
    assert not registry.is_configured(registry.providers["open_library_book_search"])
    assert RegistryMatcher().match("Search books about Ada Lovelace", registry) is None


def test_runtime_fails_over_to_next_provider_and_caches_success():
    first = provider(provider_id="first", priority=1)
    second = provider(provider_id="second", priority=2)
    registry = SimpleNamespace(
        providers={"first": first, "second": second}, is_configured=lambda item: True
    )

    class FixedMatcher:
        def match(self, request, registry):
            return {
                "capability": "geocoding",
                "parameters": {"name": "Delhi"},
                "provider_ids": ("first", "second"),
                "confidence": 0.96,
                "explanation": "unit test",
            }

    class FakeExecutor:
        def __init__(self):
            self.calls = []

        def execute(self, item, params):
            self.calls.append(item.provider_id)
            if item.provider_id == "first":
                raise APIRequestError("offline", reachable=False)
            response = APIResponse(
                item.provider_id,
                "geocoding",
                {"results": []},
                200,
                "application/json",
                "2026-10-02T00:00:00+00:00",
                "a" * 64,
            )
            return response, 2.5, {"response_valid": True, "schema_valid": True}

    executor = FakeExecutor()
    runtime = APIRegistryRuntime(
        registry=registry,
        matcher=FixedMatcher(),
        executor=executor,
        cache=APIResponseCache(),
        health=ProviderHealthMonitor(),
    )
    matched = runtime.match("coordinates for Delhi")
    assert runtime.execute(matched).provider_id == "second"
    assert executor.calls == ["first", "second"]
    assert runtime.health.get("first")["reachable"] is False
    assert runtime.execute(matched).cache_hit is True
    assert executor.calls == ["first", "second"]


@pytest.mark.parametrize("selected", ["anthropic", "nvidia"])
def test_unsupported_request_keeps_selected_existing_provider(selected):
    class NoTaskEngine:
        def classify(self, content, web_mode=False):
            return None

    graph, matched = classify_chat_routes(
        "Explain why this code is slow",
        NoTaskEngine(),
        APIRegistryRuntime(registry=APIRegistry()),
    )
    assert graph is None and matched is None
    assert select_chat_provider(graph, matched, selected) == selected


def test_unrecognized_currency_units_can_route_to_registry(monkeypatch):
    inputs = {"value": 10, "source": "usd", "target": "inr"}
    graph = SimpleNamespace(
        kind="unit_conversion", nodes=[SimpleNamespace(inputs=inputs)]
    )

    class CurrencyIntentEngine:
        def classify(self, content, web_mode=False):
            return graph

    registry = APIRegistryRuntime(registry=APIRegistry())
    routed_graph, matched = classify_chat_routes(
        "Convert 10 USD to INR", CurrencyIntentEngine(), registry
    )
    assert routed_graph is None
    assert matched.capability == "currency_rate"


def test_catalogue_discovery_does_not_create_executable_provider_implicitly(tmp_path):
    parsed = parse_catalog(
        "### Science\nAPI | Description | Auth | HTTPS | CORS\n|---|---|---|---|---|\n"
        "| [Only discovered](https://docs.example) | API listing | No | Yes | Unknown |",
        "fixture-commit",
    )
    catalog_path = tmp_path / "api_catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [item.to_dict() for item in parsed.entries],
            }
        ),
        encoding="utf-8",
    )
    provider_dir = tmp_path / "providers"
    provider_dir.mkdir()
    registry = APIRegistry(catalog_path, provider_dir)
    assert len(registry.entries) == 1
    assert registry.providers == {}
    assert registry.candidates("geocoding") == []
