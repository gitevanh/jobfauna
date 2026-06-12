"""
ratelimit.py
------------
A tiny in-memory rate limiter — no Redis, no extra dependencies. Good for a
single-process app like this one (the default `python main.py`).

It uses a sliding window: it remembers the timestamps of recent attempts for a
key (e.g. an IP address) and refuses new ones once there are too many inside the
window. We use it to stop brute-force password guessing on /api/login and to
stop spam on /api/request-access.

Thread-safe: FastAPI runs our sync endpoints in a threadpool, so several requests
can touch the limiter at once — hence the lock.
"""

import time
import threading
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_attempts, window_seconds):
        self.max = max_attempts
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()
        self._since_cleanup = 0

    def _prune(self, key, now):
        dq = self._hits[key]
        cutoff = now - self.window
        while dq and dq[0] <= cutoff:
            dq.popleft()

    def allowed(self, key):
        """True if another attempt is allowed right now."""
        now = time.time()
        with self._lock:
            self._prune(key, now)
            return len(self._hits[key]) < self.max

    def record(self, key):
        """Record one attempt against the key."""
        now = time.time()
        with self._lock:
            self._hits[key].append(now)
            self._maybe_cleanup(now)

    def retry_after(self, key):
        """Seconds until the oldest attempt rolls out of the window (>=1)."""
        now = time.time()
        with self._lock:
            self._prune(key, now)
            dq = self._hits[key]
            if len(dq) < self.max:
                return 0
            return int(dq[0] + self.window - now) + 1

    def reset(self, key):
        """Clear a key's history — e.g. after a successful login."""
        with self._lock:
            self._hits.pop(key, None)

    def _maybe_cleanup(self, now):
        """Occasionally drop empty buckets so the dict doesn't grow forever."""
        self._since_cleanup += 1
        if self._since_cleanup < 500:
            return
        self._since_cleanup = 0
        for k in list(self._hits.keys()):
            self._prune(k, now)
            if not self._hits[k]:
                del self._hits[k]


def client_ip(request):
    """
    Best-effort real client IP. Behind Cloudflare/Nginx the socket IP is the
    proxy's, so we prefer the forwarded headers those proxies set.

    NOTE: these headers are only trustworthy behind a proxy you control (which is
    the recommended deployment). Don't expose the app directly to the internet.
    """
    cf = request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
