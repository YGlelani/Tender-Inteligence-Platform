"""
Ollama embeddings client.

Uses the Ollama /api/embeddings endpoint with nomic-embed-text.
No paid APIs. Runs on the existing tender-ollama container.
"""
import logging
import os

import httpx

logger = logging.getLogger("tender.ai.embeddings")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_TIMEOUT = float(os.getenv("EMBED_TIMEOUT_SECONDS", "30"))


class EmbeddingError(RuntimeError):
    pass


async def embed(text: str) -> list[float]:
    """Return the embedding vector for a single piece of text."""
    if not text or not text.strip():
        raise EmbeddingError("Cannot embed empty text.")

    payload = {"model": EMBED_MODEL, "prompt": text[:8000]}
    try:
        async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
            resp = await client.post(f"{OLLAMA_BASE_URL}/api/embeddings", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise EmbeddingError(f"Ollama embeddings unavailable: {e}") from e

    vec = data.get("embedding")
    if not isinstance(vec, list) or not vec:
        raise EmbeddingError("Ollama returned an invalid embedding.")
    return vec


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts. Sequential — Ollama handles one at a time on CPU."""
    out = []
    for t in texts:
        try:
            out.append(await embed(t))
        except EmbeddingError as e:
            logger.warning("embed_batch: skipping one item (%s)", e)
            out.append([])
    return out


async def is_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            tags = resp.json().get("models", [])
        return any(EMBED_MODEL in m.get("name", "") for m in tags)
    except Exception:
        return False