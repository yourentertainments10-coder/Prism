import importlib
import json
import sys

import httpx
import pytest

from prism_superagent.api_registry.registry import APIRegistry
from prism_superagent.capabilities.ollama import OllamaModelRegistry, _parse_model
from prism_superagent.capabilities.registry import (
    Capability,
    CapabilityRegistry,
    build_capability_registry,
)
from prism_superagent.capabilities.summarization import (
    LocalDocumentSummarizer,
    ModelGeneratedResult,
)
from prism_superagent.engine.runtime import DeterministicEngine


def _tags_response():
    return {
        "models": [
            {
                "name": "local-instruct:latest",
                "size": 1024,
                "digest": "local-digest",
                "details": {"context_length": 8192},
                "capabilities": ["completion", "tools"],
            },
            {
                "name": "minimax-m2.5:cloud",
                "size": 337,
                "digest": "remote-digest",
                "remote_model": "minimax-m2.5",
                "remote_host": "https://ollama.com:443",
                "capabilities": ["completion", "thinking"],
            },
            {"name": "unknown:latest", "size": 0, "digest": ""},
        ]
    }


def test_capability_registry_registers_existing_engines_and_models():
    registry = CapabilityRegistry()
    item = Capability(
        capability_id="test:one",
        name="Test",
        description="test",
        input_requirements={},
        executor="unit_test",
        availability="available",
        verification_method="none",
        requires_model=False,
        requires_network=False,
        cost_class="local_compute",
        priority=1,
        source="test",
    )
    assert registry.register(item) == item
    assert registry.get("test:one") == item
    with pytest.raises(ValueError):
        registry.register(Capability(**{**item.__dict__, "name": "Conflict"}))

    engine = DeterministicEngine(workspace=".")
    inventory = build_capability_registry(
        engine,
        APIRegistry(),
        agent_tools=[
            {
                "type": "function",
                "function": {
                    "name": "run_python",
                    "description": "Run Python in Prism's workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {"code": {"type": "string"}},
                    },
                },
            }
        ],
        cloud_models=[{"id": "claude-sonnet-5", "provider": "anthropic"}],
        local_models=tuple(
            _parse_model(model, "2026-10-02T00:00:00Z")
            for model in _tags_response()["models"]
        ),
    )
    assert inventory.get("deterministic:arithmetic_mean") is not None
    assert inventory.get("api:currency_rate") is not None
    assert inventory.get("agent_tool:run_python") is not None
    assert (
        inventory.models(provider="ollama", classification="cloud")[0].model_id
        == "minimax-m2.5:cloud"
    )
    assert (
        inventory.get("local_model:local-instruct:latest:document_summarization")
        is not None
    )
    assert (
        inventory.get("local_model:minimax-m2.5:cloud:document_summarization") is None
    )


def test_ollama_discovery_lists_without_inference_and_separates_cloud_models():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=_tags_response())

    registry = OllamaModelRegistry(transport=httpx.MockTransport(handler))
    models = registry.refresh()

    assert registry.available
    assert calls == [("GET", "/api/tags")]
    assert [item.name for item in registry.confirmed_local_models()] == [
        "local-instruct:latest"
    ]
    cloud = next(item for item in models if item.name == "minimax-m2.5:cloud")
    assert cloud.classification == "cloud"
    assert not cloud.confirmed_local
    assert (
        next(item for item in models if item.name == "unknown:latest").classification
        == "unconfirmed"
    )


def test_ollama_unavailable_is_graceful():
    registry = OllamaModelRegistry(
        transport=httpx.MockTransport(lambda _request: httpx.Response(503))
    )
    assert registry.refresh() == ()
    assert not registry.available
    assert registry.last_error == "HTTPStatusError"


def test_ollama_rejects_non_loopback_endpoint_without_request():
    registry = OllamaModelRegistry("http://example.com:11434")
    assert registry.refresh() == ()
    assert not registry.available
    assert registry.last_error == "ValueError"


def test_cloud_tag_or_remote_metadata_never_confirms_local_inference():
    by_suffix = _parse_model(
        {"name": "model:cloud", "size": 500, "digest": "abc"}, "now"
    )
    by_remote_host = _parse_model(
        {
            "name": "model:latest",
            "size": 500,
            "digest": "abc",
            "remote_host": "https://ollama.com",
        },
        "now",
    )
    assert by_suffix.classification == "cloud"
    assert by_remote_host.classification == "cloud"
    assert not by_suffix.confirmed_local and not by_remote_host.confirmed_local


def test_local_document_summary_uses_mocked_inference_and_marks_result():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, json={"response": "The document describes three milestones."}
        )

    model = _parse_model(_tags_response()["models"][0], "now")
    summarizer = LocalDocumentSummarizer(transport=httpx.MockTransport(handler))
    result = summarizer.summarize(
        model,
        [{"filename": "plan.txt", "text": "Three milestones are listed."}],
        "Summarize this file",
    )
    assert isinstance(result, ModelGeneratedResult)
    assert result.status == "model_generated"
    assert result.verification_status == "structure_valid"
    assert result.answer.startswith("The document")
    assert requests[0]["stream"] is False
    assert requests[0]["model"] == "local-instruct:latest"


def test_local_summarizer_rejects_cloud_tagged_model():
    model = _parse_model(_tags_response()["models"][1], "now")
    summarizer = LocalDocumentSummarizer(
        transport=httpx.MockTransport(lambda _request: pytest.fail("must not infer"))
    )
    with pytest.raises(ValueError, match="confirmed local"):
        summarizer.summarize(model, [{"filename": "x.txt", "text": "text"}])


@pytest.fixture
def active_app(monkeypatch):
    memory = importlib.import_module("agent.memory")
    monkeypatch.setattr(memory, "init_db", lambda: None)
    prompt = importlib.import_module("agent.prompt")
    monkeypatch.setattr(prompt, "system_prompt", lambda *_args: "test system prompt")
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    module.app.config.update(TESTING=True)
    return module


class _FakeModelRegistry:
    def __init__(self, models):
        self.models = tuple(models)
        self.refresh_calls = 0

    def refresh(self):
        self.refresh_calls += 1
        return self.models

    def confirmed_local_models(self, capability="completion"):
        return tuple(
            item
            for item in self.models
            if item.confirmed_local and capability in item.capabilities
        )


def _document_message():
    return (
        "Summarize this document.\n\n[Attached file: notes.txt]\n```\n"
        "A brief plan with three milestones.\n```"
    )


def test_automatic_document_summary_uses_confirmed_local_model(active_app, monkeypatch):
    model = _parse_model(_tags_response()["models"][0], "now")
    models = _FakeModelRegistry([model])
    monkeypatch.setattr(active_app, "ollama_model_registry", models)

    class FakeSummarizer:
        def summarize(self, selected, documents, request_text):
            assert selected.name == model.name
            assert documents[0]["filename"] == "notes.txt"
            assert "Summarize" in request_text
            return ModelGeneratedResult("Three milestones are listed.", selected.name)

    monkeypatch.setattr(active_app, "local_document_summarizer", FakeSummarizer())
    monkeypatch.setattr(
        active_app,
        "run_agent_loop",
        lambda *args: pytest.fail("cloud fallback not expected"),
    )
    response = active_app.app.test_client().post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": _document_message()}],
            "model": "auto",
        },
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "model_generated" in body
    assert "semantic accuracy is not independently verified" in body
    assert "Three milestones are listed." in body
    assert models.refresh_calls == 1


def test_explicit_anthropic_selection_bypasses_local_router(active_app, monkeypatch):
    models = _FakeModelRegistry([_parse_model(_tags_response()["models"][0], "now")])
    monkeypatch.setattr(active_app, "ollama_model_registry", models)
    provider_calls = []

    def fake_loop(provider, model, _system, _convo, _tools, sse):
        provider_calls.append((provider, model))
        yield sse({"content": "cloud response"})
        yield sse({"done": True})

    monkeypatch.setattr(active_app, "run_agent_loop", fake_loop)
    response = active_app.app.test_client().post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": _document_message()}],
            "model": "claude-sonnet-5",
        },
    )
    assert response.status_code == 200
    assert provider_calls[0][0] is active_app.anthropic_provider
    assert provider_calls[0][1] == "claude-sonnet-5"
    assert models.refresh_calls == 0


def test_auto_without_confirmed_local_model_falls_back_to_nvidia(
    active_app, monkeypatch
):
    cloud_model = _parse_model(_tags_response()["models"][1], "now")
    models = _FakeModelRegistry([cloud_model])
    monkeypatch.setattr(active_app, "ollama_model_registry", models)
    provider_calls = []

    def fake_loop(provider, model, _system, _convo, _tools, sse):
        provider_calls.append((provider, model))
        yield sse({"content": "cloud fallback"})
        yield sse({"done": True})

    monkeypatch.setattr(active_app, "run_agent_loop", fake_loop)
    response = active_app.app.test_client().post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": _document_message()}],
            "model": "auto",
        },
    )
    assert response.status_code == 200
    assert provider_calls[0][0] is active_app.nvidia_provider
    assert "cloud fallback" in response.get_data(as_text=True)


def test_local_inference_error_falls_back_to_selected_default(active_app, monkeypatch):
    model = _parse_model(_tags_response()["models"][0], "now")
    monkeypatch.setattr(
        active_app, "ollama_model_registry", _FakeModelRegistry([model])
    )

    class BrokenSummarizer:
        def summarize(self, *_args):
            raise httpx.ConnectError("local server stopped")

    calls = []

    def fake_loop(provider, model, _system, _convo, _tools, sse):
        calls.append(provider)
        yield sse({"content": "fallback answer"})
        yield sse({"done": True})

    monkeypatch.setattr(active_app, "local_document_summarizer", BrokenSummarizer())
    monkeypatch.setattr(active_app, "run_agent_loop", fake_loop)
    response = active_app.app.test_client().post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": _document_message()}],
            "model": "auto",
        },
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert calls == [active_app.nvidia_provider]
    assert "fallback answer" in body


def test_automatic_deterministic_route_still_executes_before_models(
    active_app, monkeypatch
):
    monkeypatch.setattr(active_app, "ollama_model_registry", _FakeModelRegistry([]))
    monkeypatch.setattr(
        active_app,
        "run_agent_loop",
        lambda *args: pytest.fail("model route not expected"),
    )
    response = active_app.app.test_client().post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "Calculate the average of 10, 20, 30"}
            ],
            "model": "auto",
        },
    )
    assert response.status_code == 200
    assert "Average of 3 values: 20" in response.get_data(as_text=True)


def test_attached_document_word_count_is_deterministic_without_ollama(
    active_app, monkeypatch
):
    model = _parse_model(_tags_response()["models"][0], "now")
    models = _FakeModelRegistry([model])
    monkeypatch.setattr(active_app, "ollama_model_registry", models)
    monkeypatch.setattr(
        active_app,
        "run_agent_loop",
        lambda *args: pytest.fail("deterministic word count must not use a model"),
    )
    monkeypatch.setattr(
        active_app.api_registry_runtime,
        "execute",
        lambda *_args: pytest.fail("deterministic word count must not call an API"),
    )
    message = (
        "Count the words in this document.\n\n[Attached file: notes.txt]\n```\n"
        "Prism runs locally. No cloud call.\n```"
    )
    response = active_app.app.test_client().post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": message}], "model": "auto"},
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "notes.txt: 6 words" in body
    assert "Total: 6 words" in body
    assert models.refresh_calls == 0


def test_existing_cloud_fallback_keeps_explicit_nvidia_choice(active_app, monkeypatch):
    calls = []

    def fake_loop(provider, model, _system, _convo, _tools, sse):
        calls.append((provider, model))
        yield sse({"content": "NVIDIA response"})
        yield sse({"done": True})

    monkeypatch.setattr(active_app, "run_agent_loop", fake_loop)
    response = active_app.app.test_client().post(
        "/api/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "Explain a nuanced philosophical question.",
                }
            ],
            "model": "deepseek-ai/deepseek-v4-pro-0813",
        },
    )
    assert response.status_code == 200
    assert calls[0][0] is active_app.nvidia_provider
    assert calls[0][1] == "deepseek-ai/deepseek-v4-pro-0813"


def test_existing_api_match_remains_ahead_of_model_fallback(active_app, monkeypatch):
    from prism_superagent.api_registry.models import APIResponse

    monkeypatch.setattr(
        active_app.api_registry_runtime,
        "execute",
        lambda match: APIResponse(
            provider_id="frankfurter_currency_rate",
            capability="currency_rate",
            data={"date": "2026-10-01", "base": "USD", "quote": "EUR", "rate": 0.85},
            status=200,
            content_type="application/json",
            retrieved_at="2026-10-01T00:00:00Z",
            sha256="test-hash",
        ),
    )
    monkeypatch.setattr(
        active_app,
        "run_agent_loop",
        lambda *args: pytest.fail("API route should answer"),
    )
    response = active_app.app.test_client().post(
        "/api/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "What is the exchange rate for USD to EUR?",
                }
            ],
            "model": "auto",
        },
    )
    assert response.status_code == 200
    assert "EUR" in response.get_data(as_text=True)
