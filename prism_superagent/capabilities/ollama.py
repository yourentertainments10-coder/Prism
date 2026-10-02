"""Read-only discovery of locally stored Ollama models."""

import ipaddress
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True)
class OllamaModel:
    name: str
    available: bool
    classification: str
    confirmed_local: bool
    capabilities: tuple[str, ...]
    discovered_at: str
    size: int | None = None
    digest: str | None = None
    context_length: int | None = None
    remote_host: str | None = None
    details: dict | None = None


class OllamaModelRegistry:
    """Use only Ollama's local /api/tags endpoint; never pull or infer here."""

    def __init__(self, base_url="http://127.0.0.1:11434", timeout=1.5, transport=None):
        try:
            self.base_url = _local_base_url(base_url)
        except ValueError:
            self.base_url = None
        self.timeout = timeout
        self.transport = transport
        self.available = False
        self.last_error = None
        self.discovered_at = None
        self._models = ()

    def refresh(self):
        now = datetime.now(timezone.utc).isoformat()
        self.discovered_at = now
        self.available = False
        self.last_error = None
        self._models = ()
        try:
            if self.base_url is None:
                raise ValueError("Configured Ollama endpoint is not local loopback.")
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("Ollama model-list response must be an object.")
            raw_models = payload.get("models")
            if not isinstance(raw_models, list):
                raise TypeError("Ollama model-list response has no models array.")
            self._models = tuple(_parse_model(item, now) for item in raw_models)
            self.available = True
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self.last_error = type(exc).__name__
        return self.models

    @property
    def models(self):
        return self._models

    def confirmed_local_models(self, capability="completion"):
        return tuple(
            item
            for item in self._models
            if item.available
            and item.confirmed_local
            and (not capability or capability in item.capabilities)
        )


def _parse_model(item, discovered_at):
    if not isinstance(item, dict):
        raise TypeError("Ollama model-list entry must be an object.")
    name = item.get("name") or item.get("model")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Ollama model-list entry is missing a name.")
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    remote_host = item.get("remote_host") or item.get("remoteHost")
    capabilities = item.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
    cloud_tagged = (
        name.casefold().endswith(":cloud")
        or bool(item.get("remote_model") or item.get("remoteModel"))
        or bool(remote_host)
    )
    size = item.get("size")
    size = size if isinstance(size, int) and size > 0 else None
    digest = item.get("digest")
    confirmed_local = bool(
        not cloud_tagged
        and size is not None
        and isinstance(digest, str)
        and digest.strip()
    )
    context_length = details.get("context_length") or details.get("contextLength")
    context_length = (
        context_length
        if isinstance(context_length, int) and context_length > 0
        else None
    )
    classification = (
        "cloud" if cloud_tagged else "local" if confirmed_local else "unconfirmed"
    )
    return OllamaModel(
        name=name,
        available=True,
        classification=classification,
        confirmed_local=confirmed_local,
        capabilities=tuple(sorted({str(value) for value in capabilities})),
        discovered_at=discovered_at,
        size=size,
        digest=digest if isinstance(digest, str) else None,
        context_length=context_length,
        remote_host=remote_host if isinstance(remote_host, str) else None,
        details=details,
    )


def _local_base_url(value):
    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold()
    is_loopback = host == "localhost"
    try:
        is_loopback = is_loopback or ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host == "localhost"
    if (
        parsed.scheme != "http"
        or not is_loopback
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 11434)
    ):
        raise ValueError("Ollama discovery must use a local loopback HTTP endpoint.")
    path = parsed.path.rstrip("/")
    path = path.removesuffix("/v1")
    if path:
        raise ValueError("Ollama base URL cannot include an API path.")
    authority_host = f"[{host}]" if ":" in host else host
    return f"http://{authority_host}:11434"
