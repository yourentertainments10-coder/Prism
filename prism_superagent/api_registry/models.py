"""Typed records for discovered catalogue entries and executable providers."""

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class CatalogEntry:
    entry_id: str
    name: str
    category: str
    description: str
    auth_raw: str
    auth: str
    https_raw: str
    https: bool | None
    cors_raw: str
    cors: bool | None
    documentation_url: str
    source_repository: str
    source_commit: str
    imported_at: str
    raw_extra_cells: tuple[str, ...] = ()
    status: str = "discovered"
    health: str = "unknown"
    endpoint_verified: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        prepared = dict(value)
        prepared["raw_extra_cells"] = tuple(prepared.get("raw_extra_cells", ()))
        return cls(**prepared)


@dataclass(frozen=True)
class ReviewedProvider:
    """Executable configuration; never synthesized from a catalogue row."""

    provider_id: str
    name: str
    capability: str
    base_url: str
    allowed_hosts: tuple[str, ...]
    endpoint: str
    method: str
    query_parameters: dict[str, dict[str, Any]]
    required_parameters: tuple[str, ...]
    response_type: str
    response_schema: dict[str, Any]
    authentication_configuration: dict[str, Any]
    environment_variable_references: tuple[str, ...]
    timeout_seconds: float
    response_size_limit: int
    cache_policy: dict[str, Any]
    pricing_status: str
    authority_status: str
    verification_status: str
    catalog_entry_name: str
    catalog_category: str
    headers: dict[str, str] = field(default_factory=dict)
    header_environment: dict[str, str] = field(default_factory=dict)
    default_parameters: dict[str, Any] = field(default_factory=dict)
    path_parameters: tuple[str, ...] = ()
    priority: int = 100
    enabled: bool = True
    min_interval_seconds: float = 0.0

    @classmethod
    def from_dict(cls, value):
        prepared = dict(value)
        for key in (
            "allowed_hosts",
            "required_parameters",
            "environment_variable_references",
            "path_parameters",
        ):
            prepared[key] = tuple(prepared.get(key, ()))
        if prepared.get("method", "GET").upper() != "GET":
            raise ValueError("Only GET providers can be registered in Phase 3.")
        prepared["method"] = "GET"
        provider = cls(**prepared)
        provider.validate()
        return provider

    def validate(self):
        if not self.provider_id or not self.capability or not self.allowed_hosts:
            raise ValueError("Provider ID, capability, and allowed_hosts are required.")
        if self.response_type not in ("json", "text"):
            raise ValueError("Provider response_type must be 'json' or 'text'.")
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("Provider timeout must be between 0 and 60 seconds.")
        if not 0 < self.response_size_limit <= 10_000_000:
            raise ValueError(
                "Provider response limit must be between 1 byte and 10 MB."
            )
        if not 0 <= self.min_interval_seconds <= 60:
            raise ValueError(
                "Provider minimum request interval must be between 0 and 60 seconds."
            )
        if not self.endpoint.startswith("/") or self.endpoint.startswith("//"):
            raise ValueError(
                "Provider endpoint must be a fixed path beginning with one slash."
            )
        endpoint = urlsplit(self.endpoint)
        if (
            endpoint.scheme
            or endpoint.netloc
            or endpoint.query
            or endpoint.fragment
            or "\\" in self.endpoint
        ):
            raise ValueError(
                "Provider endpoint cannot contain a host, query, fragment, or backslash."
            )
        if ".." in endpoint.path.split("/"):
            raise ValueError("Provider endpoint cannot contain parent path segments.")
        host_set = {host.lower().rstrip(".") for host in self.allowed_hosts}
        if not host_set or any("/" in host or ":" in host for host in host_set):
            raise ValueError("allowed_hosts must contain bare hostnames only.")
        if any(
            not name or not name.replace("_", "").isalnum()
            for name in self.path_parameters
        ):
            raise ValueError("Path parameter names must be simple identifiers.")
        if any(name not in self.query_parameters for name in self.required_parameters):
            raise ValueError(
                "Required query parameters must be declared in query_parameters."
            )
        if any(name not in self.query_parameters for name in self.default_parameters):
            raise ValueError("Default parameters must be declared in query_parameters.")
        if self.method != "GET":
            raise ValueError("Only GET providers can be registered in Phase 3.")
        if self.authentication_configuration.get("type", "none") not in (
            "none",
            "bearer",
            "header",
        ):
            raise ValueError("Unsupported provider authentication configuration.")
        return self


@dataclass(frozen=True)
class ProviderMatch:
    capability: str
    parameters: dict[str, Any]
    provider_ids: tuple[str, ...]
    confidence: float
    explanation: str


@dataclass(frozen=True)
class APIResponse:
    provider_id: str
    capability: str
    data: Any
    status: int
    content_type: str
    retrieved_at: str
    sha256: str
    result_status: str = "api_validated"
    cache_hit: bool = False
    confidence: float = 1.0
    match_explanation: str = ""
    requested_amount: str | None = None

    def to_dict(self):
        return asdict(self)
