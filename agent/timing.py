"""Small request-scoped timing helpers for Prism's streaming path."""

import contextvars
import json
import logging
import time

from prism_superagent.tracing import record_trace

_request = contextvars.ContextVar("prism_timing_request", default=None)
_logger = logging.getLogger("prism.timing")
_logger.setLevel(logging.INFO)
_logger.propagate = False
if not any(getattr(handler, "_prism_timing_handler", False)
           for handler in _logger.handlers):
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _handler._prism_timing_handler = True
    _logger.addHandler(_handler)


def start_request(request_id):
    """Set the request timing context and return its reset token."""
    started = time.perf_counter()
    token = _request.set((request_id, started))
    record("request_start", elapsed_ms=0)
    return token, started


def bind_request(request_id, started):
    """Restore the request timing context while a deferred stream is consumed."""
    return _request.set((request_id, started))


def end_request(token):
    _request.reset(token)


def clear_request():
    """Clear timing state when a request exits before its stream is consumed."""
    _request.set(None)


def record(event, **fields):
    record_trace(event, **fields)
    context = _request.get()
    data = {"event": event}
    if context:
        request_id, started = context
        data["request_id"] = request_id
        data["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    data.update(fields)
    _logger.info("prism_timing %s", json.dumps(data, separators=(",", ":")))


def elapsed_ms(started):
    return round((time.perf_counter() - started) * 1000, 2)
