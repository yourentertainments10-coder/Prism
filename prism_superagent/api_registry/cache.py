"""Bounded, success-only response cache for reviewed read-only providers."""

import hashlib
import json
import threading
import time
from collections import OrderedDict


class APIResponseCache:
    def __init__(self, max_entries=128, max_bytes=8_000_000):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._items = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    @staticmethod
    def key(provider_id, parameters, credential_values=()):
        # Secrets contribute only a digest for cache isolation; raw values never
        # become keys, cached response fields, logs, or user-visible output.
        credentials_digest = hashlib.sha256(
            "\0".join(credential_values).encode()
        ).hexdigest()
        payload = json.dumps(
            {
                "provider": provider_id,
                "parameters": parameters,
                "credential_scope": credentials_digest,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key):
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            inserted, ttl, value, size = item
            if ttl is not None and time.monotonic() - inserted >= ttl:
                self._remove(key, size)
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key, value, ttl, success=True):
        if not success or ttl <= 0:
            return False
        try:
            size = len(
                json.dumps(value, ensure_ascii=False, default=_json_default).encode(
                    "utf-8"
                )
            )
        except (TypeError, ValueError):
            return False
        if size > self.max_bytes:
            return False
        with self._lock:
            previous = self._items.pop(key, None)
            if previous:
                self._bytes -= previous[3]
            self._items[key] = (time.monotonic(), ttl, value, size)
            self._bytes += size
            while len(self._items) > self.max_entries or self._bytes > self.max_bytes:
                _oldest_key, oldest = self._items.popitem(last=False)
                self._bytes -= oldest[3]
        return True

    def clear(self):
        with self._lock:
            self._items.clear()
            self._bytes = 0

    def __len__(self):
        with self._lock:
            return len(self._items)

    def _remove(self, key, size):
        self._items.pop(key, None)
        self._bytes -= size


def _json_default(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Cannot cache {type(value).__name__}.")
