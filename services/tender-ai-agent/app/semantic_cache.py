"""
Semantic cache for LLM answers.

Two layers, checked in order:

  1. Exact   semcache:x:<scope>:<sha256(normalised question)>  -> answer
             Free: no embedding call. Catches "What is a CSD number?" vs
             "what is a csd number".
  2. Vector  semcache:v:<id>  (HASH: scope, question, answer, embedding)
             KNN(1) filtered by scope. Reused only if cosine similarity >=
             SEMANTIC_CACHE_THRESHOLD. Catches "how do I register on the CSD?"
             vs "what are the steps to sign up for the Central Supplier Database?"

`scope` keeps answers from leaking between contexts. General chat uses
"chat"; questions about an indexed tender document use "doc:<tender_key>", so
the same question about two different tenders never shares an answer.

Only store answers that are safe to reuse — callers must not store answers
built from live, per-user or time-sensitive tool output.
"""
import asyncio
import hashlib
import logging
import re
import time
from collections import Counter

from .config import get_settings
from .embeddings import embed, embeddings_ready
from .redis_bin import get_redis_bin, to_str
from .vector_store import Filter, VectorIndex

logger = logging.getLogger(__name__)
settings = get_settings()

INDEX = VectorIndex("semcache", "semcache:v:", tags=("scope",))
EXACT_PREFIX = "semcache:x:"

stats: Counter = Counter()


def normalise(question: str) -> str:
    q = " ".join((question or "").lower().split())
    return re.sub(r"[\s?.!]+$", "", q)


def _exact_key(question: str, scope: str) -> str:
    return f"{EXACT_PREFIX}{scope}:{hashlib.sha256(normalise(question).encode()).hexdigest()}"


def _vector_id(question: str, scope: str) -> str:
    return hashlib.sha256(f"{scope}\x00{normalise(question)}".encode()).hexdigest()[:24]


async def lookup(question: str, scope: str = "chat") -> dict | None:
    """Return {"answer", "match", "similarity", "cached_question"} or None."""
    if not settings.semantic_cache_enabled or not question.strip():
        return None
    r = get_redis_bin()
    if r is None:
        return None

    try:
        raw = await r.get(_exact_key(question, scope))
        if raw:
            stats["exact_hits"] += 1
            return {"answer": to_str(raw), "match": "exact", "similarity": 1.0,
                    "cached_question": question}
    except Exception as e:
        logger.warning("Semantic cache exact read failed: %s", e)

    # The "same meaning" step needs an embedding. Never let it hold up the reply:
    # skip it while embeddings are down, and give it a small time budget.
    if not embeddings_ready():
        stats["misses"] += 1
        return None

    async def _vector_lookup():
        vec = await embed(question)
        return await INDEX.knn(vec, k=1, flt=Filter().tag("scope", scope),
                               return_fields=("answer", "question"))

    try:
        hits = await asyncio.wait_for(_vector_lookup(), timeout=settings.semantic_cache_lookup_budget)
    except asyncio.TimeoutError:
        logger.info("Semantic cache lookup exceeded %.1fs budget; treating as a miss",
                    settings.semantic_cache_lookup_budget)
        stats["timeouts"] += 1
        stats["misses"] += 1
        return None
    except Exception as e:
        logger.warning("Semantic cache vector lookup failed: %s", e)
        stats["errors"] += 1
        return None

    if hits and hits[0].score >= settings.semantic_cache_threshold:
        stats["semantic_hits"] += 1
        h = hits[0]
        logger.info("Semantic cache HIT (%.3f)", h.score)
        return {"answer": h.fields.get("answer", ""), "match": "semantic",
                "similarity": round(h.score, 4), "cached_question": h.fields.get("question")}

    stats["misses"] += 1
    return None


async def store(question: str, answer: str, scope: str = "chat", ttl: int | None = None) -> bool:
    if not settings.semantic_cache_enabled or not answer or not question.strip():
        return False
    r = get_redis_bin()
    if r is None:
        return False
    ttl = ttl or settings.semantic_cache_ttl
    try:
        await r.set(_exact_key(question, scope), answer.encode("utf-8"), ex=ttl)
        stats["stores"] += 1
        if not embeddings_ready():
            return True  # exact-match entry is enough for now
        vec = await embed(question)  # served from the embedding cache after lookup()
        await INDEX.upsert([(_vector_id(question, scope), vec, {
            "scope": scope, "question": question[:1000], "answer": answer,
            "created_at": int(time.time()),
        })], ttl=ttl)
        return True
    except Exception as e:
        logger.warning("Semantic cache store failed: %s", e)
        return False


async def invalidate(scope: str) -> int:
    """Drop every cached answer in a scope (e.g. after a tender document is re-indexed)."""
    r = get_redis_bin()
    if r is None:
        return 0
    removed = 0
    try:
        exact = [k async for k in r.scan_iter(match=f"{EXACT_PREFIX}{scope}:*", count=500)]
        if exact:
            removed += await r.delete(*exact)
        vec_keys = []
        async for key in r.scan_iter(match=INDEX.prefix + "*", count=500):
            if to_str(await r.hget(key, "scope")) == scope.lower():
                vec_keys.append(key)
        if vec_keys:
            removed += await r.delete(*vec_keys)
    except Exception as e:
        logger.warning("Semantic cache invalidate failed: %s", e)
    return removed


def get_stats() -> dict:
    hits = stats["exact_hits"] + stats["semantic_hits"]
    total = hits + stats["misses"]
    return {
        "enabled": settings.semantic_cache_enabled,
        "threshold": settings.semantic_cache_threshold,
        "exact_hits": stats["exact_hits"],
        "semantic_hits": stats["semantic_hits"],
        "misses": stats["misses"],
        "stores": stats["stores"],
        "errors": stats["errors"],
        "lookup_timeouts": stats["timeouts"],
        "hit_rate": round(hits / total, 3) if total else None,
    }
