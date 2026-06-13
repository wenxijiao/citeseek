"""Per-host async rate limiting and polite retry for scholarly APIs.

arXiv asks for 1 request / 3 s on a single connection; Semantic Scholar's
unauthenticated pool is ~1 req/s shared across all users (429s are normal);
OpenAlex tolerates ~10 req/s with a mailto. A failed source must degrade,
not fail the pipeline — callers catch SourceError.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)


class SourceError(Exception):
    """A source failed after retries; pipeline should continue without it."""


class HostLimiter:
    """Minimum-interval limiter, one per host, shared across tasks."""

    _limiters: dict[str, "HostLimiter"] = {}

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    @classmethod
    def for_host(cls, host: str, min_interval: float) -> "HostLimiter":
        if host not in cls._limiters:
            cls._limiters[host] = cls(min_interval)
        return cls._limiters[host]

    async def acquire(self) -> None:
        async with self._lock:
            wait = self._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


async def polite_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    min_interval: float,
    params: dict | None = None,
    headers: dict | None = None,
    max_retries: int = 3,
    timeout: float = 20.0,
) -> httpx.Response:
    """GET with per-host rate limiting, Retry-After handling, and backoff."""
    host = httpx.URL(url).host
    limiter = HostLimiter.for_host(host, min_interval)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        await limiter.acquire()
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = float(resp.headers.get("Retry-After", 0) or 0)
                delay = max(retry_after, 1.5 * (2**attempt))
                logger.warning("%s returned %s, retrying in %.1fs", host, resp.status_code, delay)
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError:
            raise
        except httpx.HTTPError as exc:
            last_exc = exc
            await asyncio.sleep(1.5 * (2**attempt))
    raise SourceError(f"{host}: exhausted retries ({last_exc})")
