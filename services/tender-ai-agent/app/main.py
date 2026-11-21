import logging
import os
import asyncio
from contextlib import asynccontextmanager
import hashlib
import secrets
import shutil
import tempfile
import time
import urllib.parse
from pathlib import Path
import io

import httpx
from fastapi import FastAPI, HTTPException, Header, Request, File, UploadFile, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from .config import ai_service_headers, get_settings
from .llm import get_llm, llm_status, resolve_llm_target
from .graph import get_graph, new_message_state
from .memory import init_memory, get_memory
from .rag import indexed_documents, ingest_pdf, query_index
from . import embeddings, semantic_cache, upstream
from .redis_bin import close_redis_bin, init_redis_bin
from .tender_index import (index_size, last_sync, periodic_sync, semantic_search,
                           sync_open_tenders, tender_key)
from .vector_store import backend_info
from .auth import oauth2_scheme, user_email, verify_token
from .cache import init_cache, get_cache
from .vault import get_vault
from . import matches
from .onboarding import resume_unfinished
from .routers.onboarding import router as onboarding_router
from .account_deletion import router as account_deletion_router

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Find the Azure URL style that works; never crash startup if Azure is down.
    await resolve_llm_target()
    get_graph()
    await init_memory()
    await init_cache()
    await init_redis_bin()          # binary-safe client for vectors + embedding cache
    # Find the embedding URL in the background, before users need it (never blocks startup).
    embed_probe = asyncio.create_task(embeddings.resolve_embed_target())
    get_vault()
    await resume_unfinished()
    # Keep the semantic tender index in sync with client-api in the background.
    sync_task = asyncio.create_task(periodic_sync()) if settings.tender_sync_interval >= 0 else None
    yield
    embed_probe.cancel()
    if sync_task:
        sync_task.cancel()
    await close_redis_bin()
    await upstream.close_http_client()
    mem = get_memory()
    if mem: await mem.close()
    cache = get_cache()
    if cache: await cache.close()

# Interactive API docs (/docs, /redoc, /openapi.json) are off unless
# ENABLE_API_DOCS=true, which is meant for local development only.
_API_DOCS_ON = os.getenv("ENABLE_API_DOCS", "").strip().lower() in {"1", "true", "yes"}
API_DOCS = {} if _API_DOCS_ON else {"docs_url": None, "redoc_url": None, "openapi_url": None}

# Web pages allowed to call this API from a browser, comma-separated
# (for example https://app.example.com). Set per environment in Compose.
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if not CORS_ORIGINS:
    logging.getLogger(__name__).warning("CORS_ORIGINS is not set: browsers on other sites cannot call this API.")

app = FastAPI(**API_DOCS, title="Tender AI Agent", version="2.7.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.include_router(onboarding_router)
app.include_router(account_deletion_router)

@app.get("/health")
async def health() -> dict:
    llm = await llm_status()
    emb = await embeddings.embed_status()
    vector = await backend_info()
    ok = llm["ok"] and emb["ok"] and vector.get("redis")
    return {"status": "ok" if ok else "degraded", "service": "tender-ai-agent", "llm": llm,
            "embeddings": emb, "vector": vector,
            "tender_index": {"size": await index_size(), "last_sync": await last_sync()}}

@app.get("/agent/my-profile")
async def get_my_profile(user: dict = Depends(verify_token), token: str = Depends(oauth2_scheme)):
    try:
        # Smart Alerts' matches, so the dashboard, chat and Smart Alerts page agree.
        profile, found, source = await matches.user_matches(user.get("sub"), token)
        if profile is None:
            return {"profile": None}
        return {
            "profile_id": profile["id"],
            "profile": profile,
            "match_source": source,
            "top_matches": found,
        }
    except Exception:
        # Details go to the log, not to the browser.
        logging.getLogger(__name__).exception("Could not load business profile matches")
        raise HTTPException(502, "Could not load your business profile right now. Please try again.")

@app.post("/agent/upload-profile-direct")
async def upload_profile_direct(file: UploadFile = File(...), user: dict = Depends(verify_token)) -> dict:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")
    
    email = user.get("sub")
    tmp_path = Path(tempfile.gettempdir()) / f"profile_{int(time.time())}.pdf"
    with tmp_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            with tmp_path.open("rb") as f:
                resp = await client.post(
                    f"{settings.ai_service_url}/api/ai/business-profile/from-pdf",
                    headers=ai_service_headers(),
                    files={"file": (tmp_path.name, f, "application/pdf")},
                    data={"user_email": email}
                )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        logging.getLogger(__name__).exception("Could not read a business profile PDF")
        raise HTTPException(502, "Could not read the profile PDF right now. Please try again.")
    finally:
        tmp_path.unlink(missing_ok=True)

@app.post("/agent/chat")
async def chat(request: Request, user: dict = Depends(verify_token),
               token: str = Depends(oauth2_scheme)) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON.")
    message = body.get("message")
    # History is stored under the signed-in user. The client's session_id only
    # separates that user's own conversations, so it can never reach someone else's.
    owner = hashlib.sha256(user_email(user).encode()).hexdigest()[:24]
    client_session = str(body.get("session_id") or "default")[:64]
    session_id = f"user:{owner}:{client_session}"
    if not message:
        raise HTTPException(400, "Field 'message' required.")

    mem = get_memory()
    history_raw = await mem.get_history(session_id) if mem else []
    chat_history = []
    for m in history_raw:
        if m.get("role") == "user": chat_history.append(HumanMessage(content=m["content"]))
        elif m.get("role") == "assistant": chat_history.append(AIMessage(content=m["content"]))

    matches.current_token.set(token)  # read by the "show my matches" step; never saved
    try:
        graph = get_graph()
        final_state = await graph.ainvoke(
            # The last 3 exchanges give the agent context.
            new_message_state(session_id, message, user_email(user), chat_history[-6:]),
            config={"configurable": {"thread_id": session_id}},
        )
    except Exception:
        logging.getLogger(__name__).exception("The assistant request failed")
        raise HTTPException(502, "The assistant could not answer right now. Please try again.")

    response_text = final_state.get("final_response", "")
    if mem:
        await mem.append(session_id, "user", message)
        await mem.append(session_id, "assistant", response_text)

    return {"response": response_text, "route": final_state.get("route", "chat")}

@app.post("/agent/bid-strategy-direct")
async def bid_strategy_direct(request: Request, user: dict = Depends(verify_token)) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON.")
    tender_number = body.get("tender_number")
    profile_id = body.get("profile_id")
    if not tender_number or profile_id is None:
        raise HTTPException(400, "tender_number and profile_id required.")
    
    try:
        tender = await upstream.get_tender(tender_number)  # Redis read-through cache
        if tender is None:
            raise HTTPException(404, "Tender not found.")
        async with httpx.AsyncClient(timeout=60) as client:
            create_resp = await client.post(
                f"{settings.ai_service_url}/api/tenders",
                headers=ai_service_headers(),
                json={
                    "title": tender.get("title", "Untitled"),
                    "organisation": tender.get("organisation_name") or tender.get("organisation"),
                    "description": tender.get("description") or tender.get("title", ""),
                    "source_url": tender.get("tender_url") or tender.get("source_url"),
                    "closing_date": str(tender.get("closing_date")) if tender.get("closing_date") else None,
                },
            )
            create_resp.raise_for_status()
            tender_id = create_resp.json()["id"]

            strategy_resp = await client.post(
                f"{settings.ai_service_url}/api/tenders/{tender_id}/bid-strategy/{profile_id}",
                headers=ai_service_headers(),
            )
            strategy_resp.raise_for_status()
            strategy = strategy_resp.json()
    except HTTPException:
        raise
    except Exception:
        logging.getLogger(__name__).exception("Bid strategy request failed")
        raise HTTPException(502, "Could not build a bid strategy right now. Please try again.")

    return {"tender_number": tender_number, "profile_id": profile_id, "strategy": strategy}

@app.get("/agent/tenders")
async def get_tenders(user: dict = Depends(verify_token)):
    try:
        return await upstream.list_tenders(status="Open", limit=50)  # Redis read-through cache
    except Exception:
        logging.getLogger(__name__).exception("Tender list request failed")
        raise HTTPException(502, "Could not load tenders right now. Please try again.")

@app.get("/agent/tasks")
async def get_agent_tasks(user: dict = Depends(verify_token)):
    return {
        "tasks": [
            {"id": "t1", "status": "todo", "priority": "High", "title": "Draft Cover Letter", "description": "The agent can draft a professional cover letter based on your profile.", "action_btn": "Draft with AI", "action_type": "proposal"},
            {"id": "t2", "status": "todo", "priority": "Compliance", "title": "Verify SARS Tax Pin", "description": "Ensure your tax compliance status is valid before submitting any bids.", "action_btn": None},
            {"id": "t3", "status": "progress", "priority": "Review", "title": "Review Strategy for 01/2026", "description": "Analyze the win probability and key requirements for this tender.", "action_btn": "View Strategy", "action_type": "strategy"},
            {"id": "t4", "status": "done", "priority": "System", "title": "Business Profile Parsed", "description": "Extracted business details and services from your PDF.", "action_btn": None}
        ]
    }

class ProposalRequest(BaseModel):
    tender_number: str
    profile_id: int

@app.post("/agent/generate-proposal")
async def generate_proposal(req: ProposalRequest, user: dict = Depends(verify_token)):
    try:
        tender = await upstream.get_tender(req.tender_number)  # Redis read-through cache
    except Exception:
        tender = None
    if tender is None:
        raise HTTPException(404, "Tender not found")
    async with httpx.AsyncClient(timeout=60) as client:

        try:
            create_resp = await client.post(
                f"{settings.ai_service_url}/api/tenders",
                headers=ai_service_headers(),
                json={
                    "title": tender.get("title"),
                    "organisation": tender.get("organisation_name"),
                    "description": tender.get("description") or tender.get("title"),
                    "closing_date": str(tender.get("closing_date")) if tender.get("closing_date") else None,
                }
            )
            tender_id = create_resp.json()["id"]
            strat_resp = await client.post(f"{settings.ai_service_url}/api/tenders/{tender_id}/bid-strategy/{req.profile_id}", headers=ai_service_headers())
            strategy = strat_resp.json()
        except Exception:
            raise HTTPException(500, "Could not fetch strategy")

    await resolve_llm_target()
    llm = get_llm()
    system_prompt = "You are an expert bid writer for South African government tenders. Write a professional cover letter based on the provided strategy. Do not use placeholders. Sign off with the company name."
    human_prompt = f"Tender: {req.tender_number}\nTitle: {tender.get('title')}\nOrg: {tender.get('organisation_name')}\nStrategy: {', '.join(strategy.get('winning_strategy', []))}\n\nWrite a 3-paragraph cover letter."
    
    try:
        response = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)])
        proposal_text = response.content
    except Exception:
        logging.getLogger(__name__).exception("Proposal generation failed")
        proposal_text = "Could not write the proposal right now. Please try again."

    return {"proposal": proposal_text}

@app.get("/agent/tenders/{tender_number:path}/documents")
async def get_tender_documents(tender_number: str, user: dict = Depends(verify_token)):
    try:
        data = await upstream.get_tender(tender_number)  # Redis read-through cache
        if data is not None:
            return {"tender_number": tender_number, "documents": data.get("documents") or [],
                    "indexed": await indexed_documents(tender_number)}
    except Exception:
        pass
    try:
        listing = await upstream.list_tenders(limit=500)
        for t in listing.get("tenders", []):
            if t.get("tender_number") == tender_number:
                return {"tender_number": tender_number, "documents": t.get("documents") or []}
    except Exception:
        pass
    return {"tender_number": tender_number, "documents": []}

class IndexRequest(BaseModel):
    tender_number: str
    document_url: str
    force: bool = False   # re-download and re-embed even if this URL is already indexed

@app.post("/agent/index-document")
async def index_document(req: IndexRequest, user: dict = Depends(verify_token)):
    try:
        chunks = await ingest_pdf(req.tender_number, req.document_url, force=req.force)
        return {"status": "success", "chunks_indexed": chunks}
    except Exception:
        logging.getLogger(__name__).exception("Could not index a tender document")
        raise HTTPException(502, "Could not index the document right now. Please try again.")

class QueryIndexRequest(BaseModel):
    tender_number: str
    question: str

@app.post("/agent/query-indexed-document")
async def query_indexed_document(req: QueryIndexRequest, user: dict = Depends(verify_token)):
    # Same (or same-meaning) question about the same tender -> cached answer.
    scope = f"doc:{tender_key(req.tender_number)}"
    hit = await semantic_cache.lookup(req.question, scope=scope)
    if hit:
        return {"answer": hit["answer"], "cached": hit["match"], "similarity": hit["similarity"]}
    try:
        chunks = await query_index(req.tender_number, req.question)
    except FileNotFoundError:
        return {"answer": "This document hasn't been indexed yet. Please click 'Index for AI' first."}
    except Exception:
        logging.getLogger(__name__).exception("Search request failed")
        raise HTTPException(502, "Search is unavailable right now. Please try again.")

    if not chunks:
        return {"answer": "I couldn't find anything relevant in the document."}

    context = "\n\n---\n\n".join(chunks)
    await resolve_llm_target()
    llm = get_llm()
    system_prompt = "You are a helpful procurement assistant. Answer the user's question based strictly on the provided document excerpts. If the answer is not there, say so."
    human_prompt = f"Excerpts:\n{context}\n\nQuestion: {req.question}"
    
    try:
        response = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)])
    except Exception:
        logging.getLogger(__name__).exception("Document question failed")
        return {"answer": "Could not answer right now. Please try again."}
    await semantic_cache.store(req.question, response.content, scope=scope)
    return {"answer": response.content, "cached": None}


# ============================================================
# Semantic tender search + cache observability
# ============================================================
class SemanticSearchRequest(BaseModel):
    query: str
    province: str | None = None
    category: str | None = None
    limit: int = 10
    open_only: bool = True


@app.post("/agent/semantic-search")
async def semantic_search_endpoint(req: SemanticSearchRequest, user: dict = Depends(verify_token)):
    """Vector search over open tenders, with optional province/category filters."""
    if not req.query.strip():
        raise HTTPException(400, "query is required")
    try:
        results = await semantic_search(req.query, province=req.province, category=req.category,
                                        limit=req.limit, open_only=req.open_only)
    except Exception:
        logging.getLogger(__name__).exception("Semantic search request failed")
        raise HTTPException(503, "Semantic search is unavailable right now. Please try again.")
    return {"query": req.query, "count": len(results), "results": results}


# Re-indexing every tender costs Azure money, so signed-in users cannot start it.
# It needs an X-Admin-Key header matching AGENT_ADMIN_KEY; without that setting
# the endpoint is switched off. The index still syncs on its own schedule.
def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("AGENT_ADMIN_KEY", "").strip()
    if not expected:
        raise HTTPException(404, "Not Found")
    if not x_admin_key or not secrets.compare_digest(x_admin_key.encode(), expected.encode()):
        raise HTTPException(403, "Forbidden")


@app.post("/agent/reindex-tenders", dependencies=[Depends(require_admin_key)])
async def reindex_tenders():
    """Re-sync open tenders into the vector index now (only changed tenders are re-embedded)."""
    return await sync_open_tenders()


@app.get("/agent/cache/stats")
async def cache_stats(user: dict = Depends(verify_token)):
    return {
        "vector_backend": await backend_info(),
        "tender_index": {"size": await index_size(), "last_sync": await last_sync()},
        "embeddings": embeddings.get_stats(),
        "semantic_cache": semantic_cache.get_stats(),
        "upstream_cache": upstream.get_stats(),
    }

@app.get("/")
async def root() -> dict:
    return {"message": "Tender AI Agent v2.7.0"}
