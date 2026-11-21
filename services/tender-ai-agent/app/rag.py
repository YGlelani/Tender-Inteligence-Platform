"""
RAG over tender documents, stored in Redis.

Before: one FAISS index per tender in /tmp — lost on every container restart,
not shared between replicas, and every chunk embedded with its own API call.

Now:
  ingest_pdf(tender, url)
    download -> pdfplumber text -> overlapping chunks
    -> embed_many()  (batched, embedding-cached)
    -> HASH rag:chunk:<tender_key>:<doc_id>:<n>  {tender_key, doc_id, chunk_index, text, source_url, embedding}
    -> HASH rag:doc:<tender_key>:<doc_id>  (metadata; re-indexing the same URL is skipped)
    -> drop cached answers for this tender (semantic cache scope "doc:<tender_key>")

  query_index(tender, question)
    embed(question) -> KNN over chunks filtered to @tender_key -> top chunk texts

Public signatures are unchanged, so main.py endpoints work as before.
"""
import hashlib
import io
import logging
import time

import httpx
import pdfplumber

from . import semantic_cache
from .embeddings import embed, embed_many
from .redis_bin import get_redis_bin, to_str
from .tender_index import tender_key
from .vector_store import Filter, VectorIndex, VectorStoreUnavailable

logger = logging.getLogger(__name__)

CHUNKS = VectorIndex("ragchunks", "rag:chunk:", tags=("tender_key", "doc_id"),
                     numerics=("chunk_index",))
DOC_META = "rag:doc:"
DOC_SET = "rag:docs:"


def doc_id_for(url: str) -> str:
    return hashlib.sha1(url.strip().encode()).hexdigest()[:16]


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    """~chunk_size-character chunks on word boundaries; consecutive chunks share
    ~overlap characters so a sentence cut at a boundary is still whole in one chunk."""
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(words):
        length, end = 0, start
        while end < len(words) and length < chunk_size:
            length += len(words[end]) + 1
            end += 1
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        back, carried = end, 0
        while back > start + 1 and carried < overlap:
            back -= 1
            carried += len(words[back]) + 1
        start = back
    return chunks


def _require_redis():
    r = get_redis_bin()
    if r is None:
        raise VectorStoreUnavailable("Document search needs Redis, which is not connected.")
    return r


async def ingest_pdf(tender_number: str, pdf_url: str, force: bool = False) -> int:
    """Download, chunk, embed and store a tender PDF. Returns the number of chunks."""
    r = _require_redis()
    tkey, did = tender_key(tender_number), doc_id_for(pdf_url)
    meta_key = f"{DOC_META}{tkey}:{did}"

    if not force:
        existing = await r.hget(meta_key, "chunks")
        if existing:
            logger.info("%s already indexed (%s chunks); skipping", pdf_url, to_str(existing))
            return int(to_str(existing))

    logger.info("Downloading PDF for %s...", tender_number)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(pdf_url)
        resp.raise_for_status()
        pdf_bytes = resp.content

    text = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"
    if not text.strip():
        raise ValueError("PDF is a scanned image. No text found.")

    chunks = chunk_text(text)
    logger.info("%s: %s chunks, embedding in batches...", tender_number, len(chunks))
    vectors = await embed_many(chunks)

    await CHUNKS.delete_matching(f"{tkey}:{did}:*")  # replace an older version of this doc
    await CHUNKS.upsert([
        (f"{tkey}:{did}:{i}", vec, {
            "tender_key": tkey, "doc_id": did, "chunk_index": i,
            "text": chunk, "source_url": pdf_url, "tender_number": tender_number,
        })
        for i, (chunk, vec) in enumerate(zip(chunks, vectors))
    ])
    await r.hset(meta_key, mapping={
        "chunks": str(len(chunks)), "url": pdf_url, "tender_number": tender_number,
        "indexed_at": str(int(time.time())),
    })
    await r.sadd(f"{DOC_SET}{tkey}", did)

    # Answers cached for this tender may now be incomplete or wrong.
    await semantic_cache.invalidate(f"doc:{tkey}")
    logger.info("Indexed %s chunks for %s", len(chunks), tender_number)
    return len(chunks)


async def query_index(tender_number: str, question: str, top_k: int = 3) -> list[str]:
    """Most relevant chunk texts for `question` within this tender's documents."""
    r = _require_redis()
    tkey = tender_key(tender_number)
    if not await r.exists(f"{DOC_SET}{tkey}"):
        raise FileNotFoundError("Document not indexed yet.")

    vec = await embed(question)
    hits = await CHUNKS.knn(vec, k=top_k, flt=Filter().tag("tender_key", tkey),
                            return_fields=("text", "chunk_index", "source_url"),
                            scan_suffix=f"{tkey}:*")
    return [h.fields.get("text", "") for h in hits if h.fields.get("text")]


async def indexed_documents(tender_number: str) -> list[dict]:
    r = get_redis_bin()
    if r is None:
        return []
    tkey = tender_key(tender_number)
    out = []
    for did in await r.smembers(f"{DOC_SET}{tkey}"):
        meta = await r.hgetall(f"{DOC_META}{tkey}:{to_str(did)}")
        out.append({to_str(k): to_str(v) for k, v in meta.items()})
    return out
