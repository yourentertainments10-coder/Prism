"""Bounded process-local cache for deterministic results."""

import hashlib
import json
import threading
import time
from collections import OrderedDict


class ResultCache:
    def __init__(self, max_entries=128):
        self.max_entries = max_entries
        self._items = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def key(graph):
        payload = json.dumps({"kind": graph.kind, "goal": graph.goal,
                              "nodes": [{"op": n.operation, "inputs": _jsonable(n.inputs)}
                                        for n in graph.nodes]},
                             sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key):
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            stored_at, ttl, value = item
            if ttl is not None and time.monotonic() - stored_at >= ttl:
                self._items.pop(key, None)
                return None
            if item is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key, value, ttl=None):
        with self._lock:
            self._items[key] = (time.monotonic(), ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "as_tuple"):
        return str(value)
    return value

