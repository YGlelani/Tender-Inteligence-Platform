"""
Async HTTP client for talking to the upstream client-api.

Wraps httpx.AsyncClient as a singleton so we reuse connections
across requests instead of opening a new TCP handshake each time.
"""
import logging
from typing import Any, Optional

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class UpstreamClient:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Open the connection pool. Called once at app startup."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Accept": "application/json"},
        )
        logger.info("Upstream client pointed at %s", self.base_url)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            logger.info("Upstream client closed")

    async def get(self, path: str, params: Optional[dict] = None) -> dict:
        """
        GET a path from the upstream client-api.
        Raises httpx.HTTPError on network/HTTP failure.
        """
        if self._client is None:
            raise RuntimeError("Upstream client not initialized")

        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def is_healthy(self) -> bool:
        """Quick health probe — used at startup and by /health."""
        if self._client is None:
            return False
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except Exception:
            return False


# Singleton
upstream: UpstreamClient | None = None


def init_upstream() -> UpstreamClient:
    global upstream
    if upstream is None:
        upstream = UpstreamClient(settings.client_api_url, settings.upstream_timeout)
    return upstream


def get_upstream() -> UpstreamClient:
    if upstream is None:
        raise RuntimeError("Upstream client not initialized — call init_upstream() first")
    return upstream