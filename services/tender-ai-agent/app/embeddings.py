"""
Embedding service with a Redis embedding cache.

  text ──► sha256 ──► Redis GET emb:<model>:<hash>
                          │ hit  → float32 vector (no API call)
                          │ miss → batched Azure embeddings call → SET with TTL

Why cache embeddings?
  * The same text gets embedded again and again: tender descriptions on every
    re-sync, repeated user questions in the semantic cache, PDFs indexed twice.
  * An embedding is deterministic for (model, text), so caching it is always
    safe. The model name is part of the key, so switching models never mixes
    vectors from two different embedding spaces.

All vectors are L2-normalised, so cosine similarity == dot product. That keeps
the brute-force fallback in vector_store.py simple and matches Redis COSINE.
"""
import asyncio
import hashlib
import logging
import time
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .config import get_settings
from .redis_bin import get_redis_bin

logger = logging.getLogger(__name__)
settings = get_settings()

# text-embedding-3-* accepts 8191 tokens; ~8000 chars stays well under that.
MAX_CHARS = 8000

stats: Counter = Counter()


class EmbeddingError(RuntimeError):
    pass


# ---------------------------------------------------------------- vectors
def to_bytes(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_bytes(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.float32)


def normalize(vec) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm else arr


def _clean(text: str) -> str:
    text = " ".join((text or "").split())
    return text[:MAX_CHARS] or " "


def cache_key(text: str, model: str | None = None) -> str:
    model = model or settings.embed_model
    return f"emb:{model}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


# ---------------------------------------------------------------- Azure connection
# The embedding deployment is a different model from the chat (Mistral) deployment,
# and Azure may serve it under a different URL style, so it gets its own probe
# instead of borrowing the chat connection's URL.
RETRY_FAILED_AFTER = 60  # seconds before re-probing a failed connection


@dataclass
class _Conn:
    target: object = None      # llm.Target that answered, or None
    ok: bool = False
    checked_at: float = 0.0
    attempts: list = field(default_factory=list)


_conn = _Conn()
_conn_lock = asyncio.Lock()
_clients: dict = {}


def _endpoint() -> str:
    return settings.azure_embed_endpoint or settings.azure_ai_endpoint


def _api_key() -> str:
    return settings.azure_embed_api_key or settings.azure_ai_api_key


async def _probe(client, target) -> dict:
    import httpx
    try:
        resp = await client.post(
            target.base_url + "embeddings",
            params=dict(target.query),
            headers={"api-key": _api_key(), "Authorization": f"Bearer {_api_key()}"},
            json={"model": settings.embed_model, "input": ["ok"]},
        )
    except httpx.HTTPError as e:
        return {"mode": target.mode, "ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    if resp.status_code == 200:
        return {"mode": target.mode, "ok": True, "status": 200}
    return {"mode": target.mode, "ok": False, "status": resp.status_code, "error": resp.text[:200]}


async def resolve_embed_target(force: bool = False) -> bool:
    """Find the URL style that serves EMBED_MODEL. Returns True when connected."""
    if not (_endpoint() and _api_key() and settings.embed_model):
        _conn.attempts = [{"ok": False, "error": "AZURE_AI_ENDPOINT / AZURE_AI_API_KEY / EMBED_MODEL not set"}]
        return False
    if not force and _conn.ok:
        return True
    if not force and _conn.checked_at and time.time() - _conn.checked_at < RETRY_FAILED_AFTER:
        return False

    import httpx
    from .llm import _candidates

    async with _conn_lock:
        # Another request finished a probe while we waited for the lock.
        if not force and (_conn.ok or (_conn.checked_at and time.time() - _conn.checked_at < RETRY_FAILED_AFTER)):
            return _conn.ok
        attempts, found = [], None
        async with httpx.AsyncClient(timeout=settings.embed_timeout) as client:
            for target in _candidates(_endpoint(), settings.embed_model):
                result = await _probe(client, target)
                attempts.append(result)
                if result["ok"]:
                    found = target
                    break
        _conn.target, _conn.ok = found, found is not None
        _conn.attempts, _conn.checked_at = attempts, time.time()

    if _conn.ok:
        logger.info("Embeddings connected: model=%s mode=%s base_url=%s",
                    settings.embed_model, _conn.target.mode, _conn.target.base_url)
    else:
        logger.error("Embeddings unreachable for model %s. Tried: %s", settings.embed_model,
                     "; ".join(f"{a['mode']} -> {a.get('status', '')} {a.get('error', '')}".strip()
                               for a in attempts))
    return _conn.ok


def _azure_client():
    from openai import AsyncOpenAI

    t = _conn.target
    key = (t.base_url, t.query)
    if key not in _clients:
        # max_retries=0: the circuit breaker below handles failures; SDK retries
        # only multiply the time a user waits on a broken endpoint.
        _clients[key] = AsyncOpenAI(base_url=t.base_url, api_key=_api_key(),
                                    default_headers={"api-key": _api_key()},
                                    default_query=dict(t.query) or None,
                                    timeout=settings.embed_timeout, max_retries=0)
    return _clients[key]


async def _call_embedding_api(texts: list[str]) -> list[list[float]]:
    if not await resolve_embed_target():
        raise EmbeddingError(f"Embedding deployment '{settings.embed_model}' is not reachable")
    resp = await _azure_client().embeddings.create(model=settings.embed_model, input=texts)
    # The API may return items out of order; `index` says which input each is for.
    return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]


# Swappable for tests.
_embedder = _call_embedding_api


def set_embedder(fn) -> None:
    global _embedder
    _embedder = fn
    reset_breaker()


# ---------------------------------------------------------------- circuit breaker
# After a failure, embeddings are skipped for EMBED_BREAKER_SECONDS so that the
# chat and search paths fall back immediately instead of each waiting for the
# same timeout. Cached embeddings are still served while the breaker is open.
_breaker = {"open_until": 0.0, "last_error": None}


def reset_breaker() -> None:
    _breaker["open_until"], _breaker["last_error"] = 0.0, None


def embeddings_available() -> bool:
    return time.time() >= _breaker["open_until"]


_probe_task: asyncio.Task | None = None


def embeddings_ready() -> bool:
    """True when embedding a *new* text should be quick: the Azure connection is
    known to work and the breaker is closed.

    Request paths (chat, search) check this before embedding so they never wait
    on the connection probe. If the connection isn't known to work, a probe is
    started in the background and the caller falls back for now.
    """
    global _probe_task
    if _embedder is not _call_embedding_api:  # tests / custom embedder: no Azure probe
        return embeddings_available()
    if _conn.ok:
        return embeddings_available()
    stale = not _conn.checked_at or time.time() - _conn.checked_at >= RETRY_FAILED_AFTER
    if stale and (_probe_task is None or _probe_task.done()):
        try:
            _probe_task = asyncio.get_running_loop().create_task(resolve_embed_target())
        except RuntimeError:
            pass  # no running loop
    return False


def _trip(error: Exception) -> None:
    _breaker["open_until"] = time.time() + settings.embed_breaker_seconds
    _breaker["last_error"] = str(error)[:300]
    logger.warning("Embeddings disabled for %ss after error: %s", settings.embed_breaker_seconds, error)


# ---------------------------------------------------------------- public API
async def embed_many(texts: list[str]) -> list[np.ndarray]:
    """Embed many texts: cache lookup with one MGET, then batched API calls for misses."""
    if not texts:
        return []
    cleaned = [_clean(t) for t in texts]
    keys = [cache_key(t) for t in cleaned]
    out: list[np.ndarray | None] = [None] * len(cleaned)

    r = get_redis_bin()
    if r is not None:
        try:
            cached = await r.mget(keys)
            for i, raw in enumerate(cached):
                if raw:
                    out[i] = from_bytes(raw)
        except Exception as e:
            logger.warning("Embedding cache read failed: %s", e)

    # Group misses by text so duplicates inside one batch are embedded once.
    pending: dict[str, list[int]] = {}
    for i, vec in enumerate(out):
        if vec is None:
            pending.setdefault(cleaned[i], []).append(i)

    hits = len(cleaned) - sum(len(v) for v in pending.values())
    stats["hits"] += hits
    stats["misses"] += len(pending)

    unique = list(pending)
    if unique and not embeddings_available():
        stats["skipped"] += 1
        raise EmbeddingError(f"Embeddings temporarily disabled: {_breaker['last_error']}")
    batch = max(1, settings.embed_batch_size)
    for start in range(0, len(unique), batch):
        chunk = unique[start:start + batch]
        try:
            vectors = await _embedder(chunk)
        except Exception as e:
            stats["errors"] += 1
            _trip(e)
            raise EmbeddingError(f"Embedding call failed: {e}") from e
        stats["api_calls"] += 1

        pipe = r.pipeline(transaction=False) if r is not None else None
        for text, raw_vec in zip(chunk, vectors):
            vec = normalize(raw_vec)
            for i in pending[text]:
                out[i] = vec
            if pipe is not None:
                pipe.set(cache_key(text), to_bytes(vec), ex=settings.embed_cache_ttl)
        if pipe is not None:
            try:
                await pipe.execute()
            except Exception as e:
                logger.warning("Embedding cache write failed: %s", e)

    return out  # type: ignore[return-value]


async def embed(text: str) -> np.ndarray:
    return (await embed_many([text]))[0]


def get_stats() -> dict:
    total = stats["hits"] + stats["misses"]
    return {
        "model": settings.embed_model,
        "hits": stats["hits"],
        "misses": stats["misses"],
        "api_calls": stats["api_calls"],
        "errors": stats["errors"],
        "skipped_while_disabled": stats["skipped"],
        "hit_rate": round(stats["hits"] / total, 3) if total else None,
    }


async def embed_status() -> dict:
    """Connection report for /health (no secrets)."""
    await resolve_embed_target()
    return {
        "ok": _conn.ok and embeddings_available(),
        "model": settings.embed_model,
        "mode": _conn.target.mode if _conn.ok else None,
        "disabled_for_seconds": max(0, round(_breaker["open_until"] - time.time())),
        "last_error": _breaker["last_error"],
        "attempts": [] if _conn.ok else _conn.attempts,
    }
