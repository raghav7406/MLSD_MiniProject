"""Per-client rate limiting using a sliding window algorithm."""
import time
import threading
from collections import defaultdict


class RateLimiter:
    def __init__(self, max_requests: int = 20, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, client_id: str) -> bool:
        with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            self._requests[client_id] = [t for t in self._requests[client_id] if t > cutoff]
            if len(self._requests[client_id]) >= self.max_requests:
                return False
            self._requests[client_id].append(now)
            return True

    def remaining(self, client_id: str) -> int:
        with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            current = [t for t in self._requests.get(client_id, []) if t > cutoff]
            return max(0, self.max_requests - len(current))


rate_limiter = RateLimiter(max_requests=20, window_seconds=60.0)

