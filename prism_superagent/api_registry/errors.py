"""Typed, deterministic API registry failures for fallback and health reporting."""


class APIRegistryError(Exception):
    pass


class ProviderConfigurationError(APIRegistryError):
    pass


class APIProvidersUnavailable(APIRegistryError):
    def __init__(self, capability, failures):
        self.capability = capability
        self.failures = tuple(failures)
        super().__init__(f"No reviewed {capability} provider completed successfully.")


class APIRequestError(APIRegistryError):
    def __init__(
        self,
        message,
        *,
        status_code=None,
        reachable=None,
        response_valid=False,
        schema_valid=False,
        latency_ms=None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.reachable = reachable
        self.response_valid = response_valid
        self.schema_valid = schema_valid
        self.latency_ms = latency_ms
