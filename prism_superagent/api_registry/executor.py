"""Safe GET-only executor for separately reviewed provider definitions."""

import hashlib
import ipaddress
import json
import os
import re
import socket
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from prism_superagent.api_registry.errors import (
    APIRequestError,
    ProviderConfigurationError,
)
from prism_superagent.api_registry.models import APIResponse, ReviewedProvider
from prism_superagent.api_registry.validator import (
    ResponseValidationError,
    ResponseValidator,
)

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class SafeAPIExecutor:
    def __init__(self, validator=None, transport=None, resolver=None):
        self.validator = validator or ResponseValidator()
        self.transport = transport
        self.resolver = resolver or socket.getaddrinfo

    def execute(self, provider: ReviewedProvider, parameters):
        if provider.method != "GET":
            raise ProviderConfigurationError("Only GET requests are enabled.")
        if not isinstance(parameters, dict):
            raise APIRequestError("Request parameters must be an object.")
        request_params = dict(parameters)
        path_values = {
            name: request_params.pop(name)
            for name in provider.path_parameters
            if name in request_params
        }
        extras = set(request_params) - set(provider.query_parameters)
        if extras:
            raise APIRequestError(
                "Request included parameters that this provider does not allow."
            )
        for name in provider.required_parameters:
            if name not in request_params or request_params[name] in (None, ""):
                raise APIRequestError(f"Missing required parameter: {name}.")
        for name in provider.path_parameters:
            if name not in path_values or path_values[name] in (None, ""):
                raise APIRequestError(f"Missing required path parameter: {name}.")
        _validate_parameters(request_params, provider.query_parameters)

        url = _build_url(provider, path_values)
        secrets = _configured_secrets(provider)
        headers = _request_headers(provider, secrets)
        _validate_url_host(url, provider.allowed_hosts, self.resolver)
        started = time.perf_counter()
        try:
            with (
                httpx.Client(
                    timeout=httpx.Timeout(
                        provider.timeout_seconds,
                        connect=min(5, provider.timeout_seconds),
                    ),
                    follow_redirects=False,
                    headers={
                        "User-Agent": "Prism-API-Registry/1.0",
                        "Accept": _accept(provider),
                        **headers,
                    },
                    transport=self.transport,
                ) as client,
                client.stream("GET", url, params=request_params) as response,
            ):
                elapsed = (time.perf_counter() - started) * 1000
                if response.is_redirect:
                    raise APIRequestError(
                        "Provider redirect refused by Prism.",
                        status_code=response.status_code,
                        reachable=True,
                        latency_ms=elapsed,
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > provider.response_size_limit:
                        raise APIRequestError(
                            "Provider response exceeded its configured size limit.",
                            status_code=response.status_code,
                            reachable=True,
                            latency_ms=elapsed,
                        )
                status = response.status_code
                content_type = response.headers.get("content-type", "")
                if status < 200 or status >= 300:
                    raise APIRequestError(
                        f"Provider returned HTTP {status}.",
                        status_code=status,
                        reachable=True,
                        latency_ms=elapsed,
                    )
                raw = bytes(body)
                try:
                    payload = self._decode(raw, content_type, provider.response_type)
                except APIRequestError as exc:
                    exc.latency_ms = elapsed
                    raise
                try:
                    validation = self.validator.validate(
                        payload, provider.response_type, provider.response_schema
                    )
                except ResponseValidationError as exc:
                    raise APIRequestError(
                        str(exc),
                        status_code=status,
                        reachable=True,
                        response_valid=True,
                        schema_valid=False,
                        latency_ms=elapsed,
                    ) from None
                payload = _redact(payload, secrets)
                retrieved_at = datetime.now(timezone.utc).isoformat()
                return (
                    APIResponse(
                        provider_id=provider.provider_id,
                        capability=provider.capability,
                        data=payload,
                        status=status,
                        content_type=content_type,
                        retrieved_at=retrieved_at,
                        sha256=hashlib.sha256(raw).hexdigest(),
                    ),
                    elapsed,
                    validation,
                )
        except APIRequestError:
            raise
        except httpx.TimeoutException as exc:
            raise APIRequestError(
                f"Provider request timed out ({type(exc).__name__}).", reachable=False
            ) from None
        except httpx.RequestError as exc:
            raise APIRequestError(
                f"Provider request failed ({type(exc).__name__}).", reachable=False
            ) from None
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise APIRequestError(
                f"Provider response could not be decoded ({type(exc).__name__}).",
                reachable=True,
                response_valid=False,
                latency_ms=(time.perf_counter() - started) * 1000,
            ) from None

    @staticmethod
    def _decode(raw, content_type, response_type):
        charset = "utf-8"
        found = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
        if found:
            charset = found.group(1).strip("\"'")
        text = raw.decode(charset, errors="strict")
        if response_type == "text":
            return text
        if not (
            "json" in content_type.casefold() or text.lstrip().startswith(("{", "["))
        ):
            raise APIRequestError(
                "Provider did not return JSON.", reachable=True, response_valid=False
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise APIRequestError(
                "Provider returned malformed JSON.",
                reachable=True,
                response_valid=False,
            ) from None


def _validate_parameters(parameters, declarations):
    for name, value in parameters.items():
        spec = declarations[name]
        kind = spec.get("type", "string")
        if kind == "string":
            valid = isinstance(value, str)
            if valid and len(value) > int(spec.get("max_length", 200)):
                valid = False
        elif kind == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif kind == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            valid = False
        if not valid:
            raise APIRequestError(
                f"Parameter '{name}' has an invalid value type or length."
            )
        if "enum" in spec and value not in spec["enum"]:
            raise APIRequestError(
                f"Parameter '{name}' is not in the provider's allowed values."
            )


def _build_url(provider, path_values):
    parsed = urlsplit(provider.base_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ProviderConfigurationError(
            "Provider base_url must be an HTTPS origin without credentials."
        )
    if parsed.port not in (None, 443) or parsed.query or parsed.fragment:
        raise ProviderConfigurationError(
            "Provider base_url cannot set a port, query, or fragment."
        )
    allowed = {item.lower().rstrip(".") for item in provider.allowed_hosts}
    if host not in allowed:
        raise ProviderConfigurationError(
            "Provider base host is not in its allowed_hosts list."
        )
    template_names = set(_PLACEHOLDER.findall(provider.endpoint))
    if template_names != set(provider.path_parameters):
        raise ProviderConfigurationError(
            "Endpoint placeholders must match declared path_parameters."
        )
    endpoint = provider.endpoint
    for name in template_names:
        endpoint = endpoint.replace(
            "{" + name + "}", quote(str(path_values[name]), safe="")
        )
    if ".." in endpoint.split("/"):
        raise ProviderConfigurationError(
            "Provider endpoint contains a parent path segment."
        )
    return urlunsplit(("https", host, parsed.path.rstrip("/") + endpoint, "", ""))


def _validate_url_host(url, allowed_hosts, resolver):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ProviderConfigurationError(
            "Only credential-free HTTPS provider URLs are allowed."
        )
    if parsed.port not in (None, 443) or host not in {
        h.lower().rstrip(".") for h in allowed_hosts
    }:
        raise ProviderConfigurationError(
            "Final request host is not allowed for this provider."
        )
    try:
        addresses = [
            ipaddress.ip_address(result[4][0])
            for result in resolver(host, parsed.port or 443, type=socket.SOCK_STREAM)
        ]
    except (OSError, ValueError, IndexError):
        raise APIRequestError(
            "Provider host could not be resolved safely.", reachable=False
        ) from None
    if not addresses or any(not address.is_global for address in addresses):
        raise ProviderConfigurationError(
            "Provider host resolved to a private or non-public address."
        )
    return parsed


def _configured_secrets(provider):
    secrets = []
    auth = provider.authentication_configuration
    env_names = list(provider.environment_variable_references) + list(
        provider.header_environment.values()
    )
    if auth.get("environment_variable"):
        env_names.append(auth["environment_variable"])
    for name in set(env_names):
        value = os.environ.get(name)
        if value:
            secrets.append(value)
    for template in provider.headers.values():
        for name in re.findall(r"\{env:([A-Z][A-Z0-9_]*)\}", template):
            value = os.environ.get(name)
            if value:
                secrets.append(value)
    return tuple(secrets)


def _request_headers(provider, secrets):
    headers = {}
    for name, template in provider.headers.items():
        headers[name] = _expand_header_template(template)
    for header, env_name in provider.header_environment.items():
        value = os.environ.get(env_name)
        if value:
            headers[header] = value
    auth = provider.authentication_configuration
    if auth.get("type") == "bearer":
        token = os.environ.get(auth.get("environment_variable", ""))
        if not token:
            raise ProviderConfigurationError(
                "Provider bearer credential is not configured."
            )
        headers["Authorization"] = "Bearer " + token
    elif auth.get("type") == "header":
        token = os.environ.get(auth.get("environment_variable", ""))
        if not token:
            raise ProviderConfigurationError("Provider credential is not configured.")
        headers[auth["header_name"]] = token
    for name, value in headers.items():
        if (
            not re.fullmatch(r"[A-Za-z0-9-]{1,64}", name)
            or "\r" in value
            or "\n" in value
        ):
            raise ProviderConfigurationError(
                "Provider header configuration is invalid."
            )
    return headers


def _expand_header_template(template):
    missing = []

    def replace_environment(found):
        value = os.environ.get(found.group(1))
        if not value:
            missing.append(found.group(1))
            return ""
        return value

    expanded = re.sub(r"\{env:([A-Z][A-Z0-9_]*)\}", replace_environment, template)
    if missing:
        raise ProviderConfigurationError(
            f"Provider header configuration is missing environment variable {missing[0]}."
        )
    return expanded


def _accept(provider):
    return (
        "application/json, text/plain;q=0.9"
        if provider.response_type == "json"
        else "text/plain, */*;q=0.1"
    )


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    return value
