"""Simple in-memory cache for retrieval results and completed runs."""
import hashlib
import json
import time
import threading
from typing import Any


class ResultCache:
    def __init__(self, ttl_seconds: float = 300.0, max_size: int = 1000):
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_key(payload: dict) -> str:
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def get(self, payload: dict) -> Any | None:
        key = self._make_key(payload)
        with self._lock:
            if key in self._cache:
                ts, value = self._cache[key]
                if time.time() - ts < self.ttl:
                    self._hits += 1
                    return value
                del self._cache[key]
            self._misses += 1
            return None

    def put(self, payload: dict, value: Any) -> None:
        key = self._make_key(payload)
        with self._lock:
            if len(self._cache) >= self.max_size:
                oldest = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest]
            self._cache[key] = (time.time(), value)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    @property
    def stats(self) -> dict:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
            "hit_rate": round(self._hits / max(1, self._hits + self._misses), 3),
        }


result_cache = ResultCache(ttl_seconds=300.0)

