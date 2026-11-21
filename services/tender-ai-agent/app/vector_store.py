"""
Vector store on Redis.

Each record is a Redis HASH:

    <prefix><id>  ->  { embedding: <float32 bytes>, tag fields..., text fields..., numeric fields... }

Two ways to search the same data:

1. Redis Query Engine (Redis 8+, or redis-stack): an HNSW index created with
   FT.CREATE and queried with KNN. Filters (tags, numeric ranges) run *inside*
   the index, before the nearest-neighbour step ("hybrid" or "pre-filtered" search).

       FT.SEARCH idx:tenders
         "(@province:{western\\ cape})=>[KNN 5 @embedding $vec AS dist]"
         PARAMS 2 vec <bytes> SORTBY dist RETURN ... DIALECT 2

2. Brute force: when the server has no FT.* commands (e.g. redis:7-alpine), we SCAN
   the hashes, filter in Python and rank by dot product with numpy. Same data,
   same results, just O(n) — fine for a few thousand records.

The store detects which one it can use, so upgrading the Redis image to redis:8
switches it to the indexed path without any code change.
"""
import logging
import re
from dataclasses import dataclass, field

import numpy as np

from .embeddings import from_bytes, to_bytes
from .redis_bin import get_redis_bin, to_str

logger = logging.getLogger(__name__)

VECTOR_FIELD = "embedding"


class VectorStoreUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------- filters
_TAG_SPECIAL = re.compile(r"([^A-Za-z0-9_])")


def norm_tag(value) -> str:
    return " ".join(str(value or "").split()).lower()


def escape_tag(value: str) -> str:
    """Escape a TAG value for the query language (spaces, '/', '-', '.', ...)."""
    return _TAG_SPECIAL.sub(r"\\\1", norm_tag(value))


@dataclass
class Filter:
    """AND of: tag fields matching any of their values, numeric fields inside any of their ranges."""
    tags: dict[str, list[str]] = field(default_factory=dict)
    ranges: dict[str, list[tuple[float, float]]] = field(default_factory=dict)

    def tag(self, name: str, *values) -> "Filter":
        vals = [norm_tag(v) for v in values if v not in (None, "")]
        if vals:
            self.tags[name] = vals
        return self

    def range(self, name: str, *spans: tuple[float, float]) -> "Filter":
        if spans:
            self.ranges[name] = list(spans)
        return self

    # --- Redis query syntax
    def to_query(self) -> str:
        parts = []
        for name, values in self.tags.items():
            parts.append(f"@{name}:{{{' | '.join(escape_tag(v) for v in values)}}}")
        for name, spans in self.ranges.items():
            alts = [f"@{name}:[{_num(lo)} {_num(hi)}]" for lo, hi in spans]
            parts.append(alts[0] if len(alts) == 1 else "(" + " | ".join(alts) + ")")
        return "(" + " ".join(parts) + ")" if parts else "*"

    # --- the same filter evaluated in Python (brute-force path)
    def matches(self, doc: dict) -> bool:
        for name, values in self.tags.items():
            if norm_tag(doc.get(name)) not in values:
                return False
        for name, spans in self.ranges.items():
            try:
                v = float(doc.get(name))
            except (TypeError, ValueError):
                return False
            if not any(lo <= v <= hi for lo, hi in spans):
                return False
        return True


def _num(x: float) -> str:
    if x == float("inf"):
        return "+inf"
    if x == float("-inf"):
        return "-inf"
    return repr(float(x)) if not float(x).is_integer() else str(int(x))


@dataclass
class Hit:
    key: str
    score: float           # cosine similarity, 1.0 = identical
    fields: dict


# ---------------------------------------------------------------- capability check
_search_supported: bool | None = None


async def search_supported() -> bool:
    """True when the server has the Redis Query Engine (FT.* commands)."""
    global _search_supported
    if _search_supported is not None:
        return _search_supported
    r = get_redis_bin()
    if r is None:
        return False
    try:
        await r.execute_command("FT._LIST")
        _search_supported = True
    except Exception:
        _search_supported = False
        logger.warning("Redis has no Query Engine (FT.*): vector search uses brute force. "
                       "Run redis:8 (or redis/redis-stack-server) for HNSW indexes.")
    return _search_supported


def reset_capability_cache() -> None:
    global _search_supported
    _search_supported = None


# ---------------------------------------------------------------- index
class VectorIndex:
    def __init__(self, name: str, prefix: str, *, tags=(), texts=(), numerics=(),
                 algorithm: str = "HNSW"):
        self.name = f"idx:{name}"
        self.prefix = prefix
        self.tags, self.texts, self.numerics = tuple(tags), tuple(texts), tuple(numerics)
        self.algorithm = algorithm
        self._ready_dim: int | None = None

    # ---- schema
    def create_args(self, dim: int) -> list:
        args = ["FT.CREATE", self.name, "ON", "HASH", "PREFIX", "1", self.prefix, "SCHEMA"]
        for t in self.tags:
            args += [t, "TAG"]
        for t in self.texts:
            args += [t, "TEXT"]
        for n in self.numerics:
            args += [n, "NUMERIC"]
        args += [VECTOR_FIELD, "VECTOR", self.algorithm, "6",
                 "TYPE", "FLOAT32", "DIM", str(dim), "DISTANCE_METRIC", "COSINE"]
        return args

    async def ensure(self, dim: int) -> None:
        """Create the index if needed; rebuild it if the embedding dimension changed."""
        if self._ready_dim == dim:
            return
        r = _require()
        if await search_supported():
            dim_key = f"{self.name}:dim"
            stored = to_str(await r.get(dim_key))
            exists = True
            try:
                await r.execute_command("FT.INFO", self.name)
            except Exception:
                exists = False
            if exists and stored and int(stored) != dim:
                logger.warning("%s: dimension %s -> %s, rebuilding index", self.name, stored, dim)
                await r.execute_command("FT.DROPINDEX", self.name)  # keeps the hashes
                exists = False
            if not exists:
                await r.execute_command(*self.create_args(dim))
                logger.info("Created vector index %s (dim=%s, %s, COSINE)", self.name, dim, self.algorithm)
            await r.set(dim_key, str(dim))
        self._ready_dim = dim

    # ---- writes
    async def upsert(self, records: list[tuple[str, np.ndarray, dict]], ttl: int | None = None) -> int:
        """records: (id, vector, fields). The key is prefix + id."""
        if not records:
            return 0
        r = _require()
        await self.ensure(len(records[0][1]))
        pipe = r.pipeline(transaction=False)
        for rid, vec, fields in records:
            key = self.prefix + rid
            mapping = {VECTOR_FIELD: to_bytes(vec)}
            for k, v in fields.items():
                if v is None:
                    continue
                mapping[k] = norm_tag(v) if k in self.tags else (v if isinstance(v, (bytes, int, float)) else str(v))
            pipe.delete(key)  # clear stale fields from an earlier version
            pipe.hset(key, mapping=mapping)
            if ttl:
                pipe.expire(key, ttl)
        await pipe.execute()
        return len(records)

    async def delete_matching(self, pattern_suffix: str = "*") -> int:
        r = _require()
        keys = [k async for k in r.scan_iter(match=self.prefix + pattern_suffix, count=500)]
        for i in range(0, len(keys), 500):
            await r.delete(*keys[i:i + 500])
        return len(keys)

    async def keys(self, pattern_suffix: str = "*") -> list[str]:
        r = _require()
        return [to_str(k) async for k in r.scan_iter(match=self.prefix + pattern_suffix, count=500)]

    # ---- reads
    async def knn(self, vec: np.ndarray, k: int = 5, flt: Filter | None = None,
                  return_fields: tuple = (), scan_suffix: str = "*") -> list[Hit]:
        """k nearest neighbours by cosine similarity, after applying `flt`.

        scan_suffix narrows the brute-force SCAN (e.g. "<tender_key>:*") and is
        ignored by the indexed path, which uses the filter instead.
        """
        r = get_redis_bin()
        if r is None:
            raise VectorStoreUnavailable("Redis is not connected")
        flt = flt or Filter()
        if await search_supported():
            try:
                await self.ensure(len(vec))
                return await self._knn_indexed(r, vec, k, flt, return_fields)
            except VectorStoreUnavailable:
                raise
            except Exception as e:
                logger.warning("%s: indexed KNN failed (%s); using brute force", self.name, e)
        return await self._knn_bruteforce(r, vec, k, flt, return_fields, scan_suffix)

    def knn_query(self, k: int, flt: Filter) -> str:
        return f"{flt.to_query()}=>[KNN {int(k)} @{VECTOR_FIELD} $vec AS dist]"

    async def _knn_indexed(self, r, vec, k, flt, return_fields) -> list[Hit]:
        fields = list(return_fields) + ["dist"]
        args = ["FT.SEARCH", self.name, self.knn_query(k, flt),
                "PARAMS", "2", "vec", to_bytes(vec),
                "SORTBY", "dist", "ASC",
                "RETURN", str(len(fields)), *fields,
                "LIMIT", "0", str(int(k)),
                "DIALECT", "2"]
        raw = await r.execute_command(*args)
        return parse_search_reply(raw)

    async def _knn_bruteforce(self, r, vec, k, flt, return_fields, scan_suffix) -> list[Hit]:
        keys = [key async for key in r.scan_iter(match=self.prefix + scan_suffix, count=500)]
        if not keys:
            return []
        q = np.asarray(vec, dtype=np.float32)
        scored: list[Hit] = []
        for i in range(0, len(keys), 200):
            batch = keys[i:i + 200]
            pipe = r.pipeline(transaction=False)
            for key in batch:
                pipe.hgetall(key)
            rows = await pipe.execute()
            for key, row in zip(batch, rows):
                if not row:
                    continue
                doc = {to_str(f): v for f, v in row.items()}
                raw_vec = doc.pop(VECTOR_FIELD, None)
                if raw_vec is None or len(raw_vec) != q.nbytes:
                    continue
                doc = {f: to_str(v) for f, v in doc.items()}
                if not flt.matches(doc):
                    continue
                sim = float(np.dot(from_bytes(raw_vec), q))
                wanted = {f: doc.get(f, "") for f in return_fields} if return_fields else doc
                scored.append(Hit(key=to_str(key), score=sim, fields=wanted))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]


def parse_search_reply(raw) -> list[Hit]:
    """Parse a RESP2 FT.SEARCH reply: [total, key1, [f, v, ...], key2, [...], ...]."""
    hits: list[Hit] = []
    if not raw:
        return hits
    items = list(raw[1:])
    for i in range(0, len(items) - 1, 2):
        key, flat = items[i], items[i + 1] or []
        doc = {to_str(flat[j]): to_str(flat[j + 1]) for j in range(0, len(flat) - 1, 2)}
        dist = float(doc.pop("dist", "1") or 1)
        hits.append(Hit(key=to_str(key), score=1.0 - dist, fields=doc))
    return hits


def _require():
    r = get_redis_bin()
    if r is None:
        raise VectorStoreUnavailable("Redis is not connected")
    return r


async def backend_info() -> dict:
    r = get_redis_bin()
    if r is None:
        return {"redis": False, "backend": None}
    supported = await search_supported()
    return {"redis": True, "backend": "redis-query-engine (HNSW)" if supported else "brute-force (numpy)"}
