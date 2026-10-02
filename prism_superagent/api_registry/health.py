"""Process-local health observations; no startup probes or automatic calls."""

import threading
from dataclasses import asdict, dataclass


@dataclass
class ProviderHealth:
    reachable: bool | None = None
    http_status: int | None = None
    latency_ms: float | None = None
    response_valid: bool | None = None
    schema_valid: bool | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_failure: str | None = None
    consecutive_failures: int = 0


class ProviderHealthMonitor:
    def __init__(self):
        self._states = {}
        self._lock = threading.RLock()

    def record_success(
        self,
        provider_id,
        http_status,
        latency_ms,
        retrieved_at,
        response_valid=True,
        schema_valid=True,
    ):
        with self._lock:
            state = self._states.setdefault(provider_id, ProviderHealth())
            state.reachable = True
            state.http_status = http_status
            state.latency_ms = round(float(latency_ms), 2)
            state.response_valid = bool(response_valid)
            state.schema_valid = bool(schema_valid)
            state.last_success_at = retrieved_at
            state.last_failure = None
            state.consecutive_failures = 0

    def record_failure(
        self,
        provider_id,
        http_status,
        latency_ms,
        failed_at,
        reason,
        reachable=None,
        response_valid=False,
        schema_valid=False,
    ):
        with self._lock:
            state = self._states.setdefault(provider_id, ProviderHealth())
            state.reachable = reachable
            state.http_status = http_status
            state.latency_ms = (
                round(float(latency_ms), 2) if latency_ms is not None else None
            )
            state.response_valid = response_valid
            state.schema_valid = schema_valid
            state.last_failure_at = failed_at
            state.last_failure = str(reason)[:300]
            state.consecutive_failures += 1

    def get(self, provider_id):
        with self._lock:
            value = self._states.get(provider_id)
            return asdict(value) if value else asdict(ProviderHealth())

    def snapshot(self):
        with self._lock:
            return {
                provider_id: asdict(state)
                for provider_id, state in self._states.items()
            }

    def is_healthy(self, provider_id):
        state = self.get(provider_id)
        return state["reachable"] is True and state["consecutive_failures"] == 0
