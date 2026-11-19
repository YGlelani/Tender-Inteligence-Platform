"""
LangGraph state machine for the tender assistant.
"""
import asyncio
import functools
import logging
import re
import time
import urllib.parse
from typing import TypedDict, Literal, Annotated

import operator

from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .config import ai_service_headers, get_settings
from . import intent, semantic_cache
from .embeddings import embeddings_ready
from .matches import current_token, run_matches, user_context
from .profile_provinces import profile_provinces
from .tender_index import detect_province, semantic_search, strip_province
from .upstream import get_tender, list_tenders, post_json
from . import ml_client

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_CLARIFY_LOOPS = 2


class AssistantState(TypedDict, total=False):
    session_id: str
    user_input: str
    user_email: str | None      # the signed-in user (set per request)
    route: str
    final_response: str
    tender_number: str | None
    profile_id: int | None
    missing: list[str]
    retry_count: int
    error: str | None
    history: Annotated[list[str], operator.add]
    chat_history: list          # recent LangChain messages for this session (set per request)


# ============================================================
# Extraction
# ============================================================
_PROFILE_ID_RE = re.compile(r'profile[_\s]?id[:\s]*(\d+)', re.IGNORECASE)

_TENDER_PREFIX_WORDS = re.compile(
    r'^\s*(?:tender|bid|rfq|rfp|ref|reference|no|number|no\.)\s*',
    re.IGNORECASE,
)

_TENDER_PATTERNS = [
    # An agency code before the number ("ACSR 116/2026", "DEDaT 12/2026") starts with two capitals,
    # so ordinary words ("for 01/2026-27", "about 12/2026") are not taken as part of the number.
    re.compile(r'\b([A-Z]{2}[A-Za-z]*[\s]+\d{2,4}\s*/\s*\d{2,4}(?:\s*-\s*\d{2,4})?)\b'),
    re.compile(r'\b(\d{1,4}\s*/\s*\d{2,4}(?:\s*[-/]\s*\d{2,4}){0,2})\b'),
    re.compile(r'\b(\d{1,4}\s*-\s*\d{2,4})\b'),
    re.compile(r'\b(\d{1,4}-\d{2,4})\b'),
    re.compile(r'\b(\d{6,})\b'),
    re.compile(r'\b(\d{2,5}[A-Za-z]{1,4}|\d{2,5}-\d[A-Za-z])\b'),
]


def _extract_tender_number(text: str) -> str | None:
    for pattern in _TENDER_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group(1)
            cleaned = _TENDER_PREFIX_WORDS.sub("", raw).strip()
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            if any(ch.isdigit() for ch in cleaned):
                return cleaned
    return None


def _extract_profile_id(text: str) -> int | None:
    m = _PROFILE_ID_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _encode_tender(tender_number: str) -> str:
    return urllib.parse.quote(tender_number, safe="")


# ============================================================
# Nodes
# ============================================================
async def load_hints(state: AssistantState) -> AssistantState:
    text = state["user_input"]
    if not state.get("tender_number"):
        state["tender_number"] = _extract_tender_number(text)
    if not state.get("profile_id"):
        state["profile_id"] = _extract_profile_id(text)
    if "retry_count" not in state:
        state["retry_count"] = 0
    state["missing"] = []
    state["error"] = None
    return state


_GENERAL_QUESTION = re.compile(
    r"^\s*(what\s+is|what's|what\s+does|how\s+do|how\s+does|how\s+can|how\s+to|why|explain|"
    r"can\s+you\s+explain|tell\s+me\s+about|define)\b",
    re.IGNORECASE,
)
_SEARCH_WORDS = ["show", "find", "list", "search", "tender", "available", "opportunit",
                 "rfq", "rfp", "contracts"]
# Questions about the assistant or the app itself, e.g. "what Tender Scrapper is".
_ABOUT_APP = re.compile(
    r"\b(tender\s*scrap+er|tender\s*os|this\s+(app|system|platform|site|website)|who\s+are\s+you|"
    r"what\s+can\s+you\s+do)\b",
    re.IGNORECASE,
)


async def classify_intent(state: AssistantState) -> AssistantState:
    text = state["user_input"].lower()
    if intent.wants_matches(text):
        # Checked first: "tenders that match my business profile" also contains "business profile".
        state["route"] = "matches"
    elif state.get("chat_history") and not state.get("tender_number") and intent.is_follow_up(text):
        # "what about Limpopo?", "the first one": only the assistant sees the earlier turns.
        state["route"] = "chat"
    elif _ABOUT_APP.search(text):
        state["route"] = "chat"
    elif any(w in text for w in ["upload", "profile pdf", "business profile"]):
        state["route"] = "uploading"
    elif intent.has_any(text, intent.DOCUMENT_WORDS):
        state["route"] = "documents"
    elif any(w in text for w in ["strategy", "how do i win", "prepare for", "how to win"]):
        state["route"] = "strategy"
    elif _GENERAL_QUESTION.match(text) and not detect_province(text):
        # "what is a tender?", "how do I register on the CSD?" -> answered by the agent,
        # which still calls a tool when the question is about specific tenders.
        state["route"] = "chat"
    elif any(w in text for w in _SEARCH_WORDS) or detect_province(text):
        state["route"] = "searching"
    else:
        state["route"] = "chat"
    return state


def route_after_classify(state: AssistantState) -> Literal[
    "matches", "uploading", "searching", "documents", "strategy", "chat", "clarify"
]:
    route = state.get("route", "chat")
    retry = state.get("retry_count", 0)

    needs_tender = route in ("documents", "strategy")
    needs_profile = route == "strategy"

    missing: list[str] = []
    if needs_tender and not state.get("tender_number"):
        missing.append("tender_number")
    if needs_profile and not state.get("profile_id"):
        missing.append("profile_id")

    if missing and retry < MAX_CLARIFY_LOOPS:
        state["missing"] = missing
        return "clarify"

    if missing:
        return "chat"

    return route


async def clarify(state: AssistantState) -> AssistantState:
    missing = state.get("missing") or []
    route = state.get("route")
    state["retry_count"] = state.get("retry_count", 0) + 1

    if "tender_number" in missing and "profile_id" in missing:
        state["final_response"] = (
            "I need both a tender number and your business profile.\n\n"
            "• Upload your business documents on Tender Scrapper, under Business Documents\n"
            "• Then include a tender number, e.g. 'give me a strategy for 01/2026-27'\n\n"
            "Or send both in one message like: 'strategy for 01/2026-27 using profile_id 12'."
        )
    elif "tender_number" in missing:
        if route == "documents":
            state["final_response"] = "Which tender would you like the documents for?\n\nSend the tender number, e.g. 'show documents for 01/2026-27'."
        else:
            state["final_response"] = "Which tender would you like a strategy for?\n\nSend the tender number, e.g. 'give me a strategy for 01/2026-27'."
    elif "profile_id" in missing:
        state["final_response"] = "I need your business profile to generate a strategy.\n\nUpload your business documents on Tender Scrapper, under Business Documents, or include your profile_id like this: 'strategy for 01/2026-27 using profile_id 12'."
    else:
        state["final_response"] = "I need a bit more information. Could you rephrase with a tender number or profile id?"

    return state


async def run_upload(state: AssistantState) -> AssistantState:
    state["final_response"] = ("Business documents are uploaded on Tender Scrapper: open Business Documents in the "
                               "menu and add your company profile there. Your matches use them once they are processed.")
    return state


_SEARCH_FILLER = re.compile(
    r"\b(show|find|list|search|get|give|me|some|any|all|the|a|an|for|of|in|on|please|"
    r"tenders?|bids?|open|available|current|latest|new|are|there|what|which|i|want|need|looking)\b",
    re.IGNORECASE,
)


def _search_terms(text: str) -> str:
    """What's left of the message after removing filler words, e.g.
    'find tenders for fixing potholes in Gauteng' -> 'fixing potholes gauteng'."""
    return " ".join(_SEARCH_FILLER.sub(" ", text).split())


def _format_tenders(header: str, tenders: list[dict], with_score: bool = False) -> str:
    lines = [header, ""]
    for t in tenders:
        num = t.get("tender_number") or "N/A"
        title = (t.get("title") or "")[:100]
        org = t.get("organisation_name") or t.get("organisation") or ""
        province = t.get("province") or "N/A"
        closing = t.get("closing_date") or "not specified"
        score = f" — match {t['score']:.0%}" if with_score and t.get("score") is not None else ""
        lines.append(f"- [{num}] {title} — {org} ({province}), closes: {closing}{score}")
    lines.append("")
    lines.append('Ask "show my matches" to see the tenders that best fit your business profile.')
    return "\n".join(lines)


def keyword_candidates(terms: str) -> list[str]:
    """Keywords to try against the database, most specific first.

    client-api matches `keyword` with SQL LIKE '%keyword%' on title, description,
    organisation and category, so a whole phrase rarely matches. Try the phrase,
    then single words (longest first, trailing plural 's' removed so 'potholes'
    also finds 'pothole').
    """
    out: list[str] = []
    phrase = " ".join(terms.split())
    if phrase:
        out.append(phrase)
    words: list[str] = []
    for w in re.findall(r"[a-z0-9]+", phrase.lower()):
        if len(w) < 4:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w not in words:
            words.append(w)
    for w in sorted(words, key=len, reverse=True)[:4]:
        if w not in out:
            out.append(w)
    return out


async def open_tenders(provinces: list[str], limit: int = 5, **filters) -> list[dict]:
    """Open tenders from the database in any of these provinces (anywhere when the list is empty).

    client-api filters one province per request, so several provinces are asked one at a time
    and merged, soonest closing first.
    """
    found: list[dict] = []
    for province in provinces or [None]:
        data = await list_tenders(status="Open", province=province, limit=limit, **filters)
        found += data.get("tenders") or []
    if len(provinces) > 1:
        found.sort(key=lambda t: str(t.get("closing_date") or "9999"))
    return found[:limit]


async def keyword_search(terms: str, provinces: list[str], limit: int = 5,
                         category: str | None = None) -> tuple[str | None, list[dict]]:
    """Search the tender database through client-api. Returns (keyword that matched, tenders)."""
    for kw in keyword_candidates(terms):
        tenders = await open_tenders(provinces, limit, keyword=kw, category=category)
        if tenders:
            return kw, tenders
    return None, []


async def _search_predicted_category(terms: str, provinces: list[str]) -> tuple[str, list[dict], bool] | None:
    """Search only inside the category tender-ml predicts: by meaning first, then by keyword.

    Returns (category, tenders, has_scores), or None so the normal search runs instead.
    """
    prediction = await ml_client.predict_category(terms)
    if not prediction:
        return None
    category = prediction["category"]
    if len(terms) >= 3 and embeddings_ready():
        try:
            hits = await semantic_search(terms, provinces=provinces, category=category, limit=5, min_score=0.25)
            if hits:
                return category, hits, True
        except Exception as e:
            logger.warning("Semantic search in the predicted category failed: %s", e)
    try:
        _, tenders = await keyword_search(terms, provinces, category=category)
    except Exception as e:
        logger.warning("Keyword search in the predicted category failed: %s", e)
        return None
    return (category, tenders, False) if tenders else None


async def _predicted_category_reply(terms: str, provinces: list[str], where: str) -> str | None:
    """The search reply when tender-ml's predicted category finds tenders, otherwise None."""
    found = await _search_predicted_category(terms, provinces) if terms else None
    if not found:
        return None
    category, hits, scored = found
    return _format_tenders(
        f"Our ML model put your request in the category \"{category}\". "
        f"Here are {len(hits)} open tenders{where} in that category for \"{terms}\":", hits, with_score=scored)


def _where(provinces: list[str], named: str | None) -> str:
    """How a search reply names the provinces it searched."""
    if named:
        return f" in {named.title()}"
    if not provinces:
        return ""
    names = ", ".join(p.title() for p in provinces if p != "national")
    return f" in your profile's provinces ({names}) or national"


async def run_search(state: AssistantState) -> AssistantState:
    text = state["user_input"]
    named = detect_province(text)
    terms = strip_province(_search_terms(text)) if named else _search_terms(text)
    # A province the user names is searched; otherwise the provinces their matches use.
    provinces = [named] if named else await profile_provinces(state.get("user_email"), current_token.get())
    where = _where(provinces, named)

    # 0. Search inside the category our ML model predicts for the request, when it is confident.
    reply = await _predicted_category_reply(terms, provinces, where)
    if reply:
        state["final_response"] = reply
        return state

    # 1. Semantic (vector) search when the user described what they want.
    #    Skipped instantly while embeddings are down, so the user never waits on it.
    if len(terms) >= 3 and embeddings_ready():
        try:
            hits = await semantic_search(terms, provinces=provinces, limit=5, min_score=0.25)
            if hits:
                state["final_response"] = _format_tenders(
                    f"Here are {len(hits)} open tenders{where} closest to \"{terms}\":", hits, with_score=True)
                return state
        except Exception as e:
            logger.warning("Semantic search unavailable, using database keyword search: %s", e)

    # 2. Keyword search in the tender database (client-api, read-through cached).
    try:
        if terms:
            kw, tenders = await keyword_search(terms, provinces)
            if tenders:
                state["final_response"] = _format_tenders(
                    f"Here are {len(tenders)} open tenders{where} matching \"{kw}\":", tenders)
                return state
        tenders = await open_tenders(provinces)
    except Exception as e:
        logger.error("run_search failed: %s", e)
        state["error"] = "search_failed"
        return state

    if not tenders:
        state["final_response"] = f"No open tenders found{where} right now."
        return state
    if terms:
        header = (f"I couldn't find open tenders matching \"{terms}\"{where}. "
                  f"Here are {len(tenders)} other open tenders{where}:")
    else:
        header = f"Here are {len(tenders)} open tenders{where}:"
    state["final_response"] = _format_tenders(header, tenders)
    return state


async def run_documents(state: AssistantState) -> AssistantState:
    tender_number = state.get("tender_number")
    if not tender_number:
        state["missing"] = ["tender_number"]
        state["route"] = "documents"
        return state

    logger.info("run_documents: %s", tender_number)

    try:
        data = await get_tender(tender_number)  # Redis read-through cache
        if data is None:
            state["final_response"] = f"Tender '{tender_number}' was not found."
            return state
    except Exception as e:
        logger.error("run_documents failed: %s", e)
        state["error"] = "documents_failed"
        return state

    docs = data.get("documents") or []
    if not docs:
        state["final_response"] = f"Tender '{tender_number}' has no documents attached."
        return state

    lines = [f"Found {len(docs)} documents for tender '{tender_number}':", ""]
    for i, d in enumerate(docs, 1):
        name = d.get("name") or d.get("document_name") or "Untitled"
        dtype = d.get("type") or d.get("document_type") or "file"
        url_ = d.get("url") or d.get("document_url") or ""
        uploaded = d.get("date_uploaded") or ""
        lines.append(f"{i}. {name} ({dtype})")
        if url_:
            lines.append(f"   Download: {url_}")
        if uploaded:
            lines.append(f"   Uploaded: {uploaded}")
        lines.append("")
    state["final_response"] = "\n".join(lines)
    return state


async def run_strategy(state: AssistantState) -> AssistantState:
    tender_number = state.get("tender_number")
    profile_id = state.get("profile_id")
    if not tender_number or not profile_id:
        state["missing"] = [
            k for k, v in (("tender_number", tender_number), ("profile_id", profile_id))
            if not v
        ]
        state["route"] = "strategy"
        return state

    try:
        tender = await get_tender(tender_number)  # Redis read-through cache
        if tender is None:
            state["final_response"] = f"Tender '{tender_number}' was not found."
            return state
        created = await post_json(
            f"{settings.ai_service_url}/api/tenders",
            {
                "title": tender.get("title", "Untitled"),
                "organisation": tender.get("organisation_name") or tender.get("organisation"),
                "description": tender.get("description") or tender.get("title", ""),
                "source_url": tender.get("tender_url") or tender.get("source_url"),
                "closing_date": str(tender.get("closing_date")) if tender.get("closing_date") else None,
            },
            headers=ai_service_headers(),
        )
        strategy = await post_json(
            f"{settings.ai_service_url}/api/tenders/{created['id']}/bid-strategy/{profile_id}",
            headers=ai_service_headers(),
        )
    except Exception as e:
        logger.error("run_strategy failed: %s", e)
        state["error"] = "strategy_failed"
        return state

    lines = [f"# Bid Strategy for {tender_number}", ""]
    lines.append(f"**Suitability score:** {strategy.get('suitability_score', 0)}/100")
    if strategy.get("industry_detected"):
        lines.append(f"**Industry detected:** {strategy['industry_detected']}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(strategy.get("summary", ""))
    lines.append("")
    for key, title in [
        ("why_this_fits", "Why This Tender Fits Your Business"),
        ("key_requirements", "Key Requirements"),
        ("documents_to_prepare", "Documents to Prepare"),
        ("winning_strategy", "Winning Strategy"),
        ("differentiators_to_highlight", "Differentiators to Highlight"),
        ("gaps_to_address", "Gaps and Risks to Address"),
        ("next_steps", "Next Steps"),
    ]:
        items = strategy.get(key) or []
        if not items:
            continue
        lines.append(f"## {title}")
        for it in items:
            lines.append(f"- {it}")
        lines.append("")
    state["final_response"] = "\n".join(lines)
    return state


# Messages that only make sense with the previous turns ("what about level 2?").
_FOLLOW_UP = re.compile(
    r"\b(it|its|that|this|those|these|them|they|above|previous|same|also|what about|and if|instead)\b",
    re.IGNORECASE,
)

_background: set = set()


def _in_background(coro) -> None:
    """Run work the user shouldn't wait for (cache writes) after the reply is ready."""
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _province_context(email: str | None) -> list[SystemMessage]:
    """Tells the assistant which provinces to search when the user names none, as the search does."""
    provinces = await profile_provinces(email, current_token.get())
    if not provinces:
        return []
    names = ", ".join(p.title() for p in provinces if p != "national")
    return [SystemMessage(content=(
        f"The user's business works in {names}, and national tenders also suit them. When you search for "
        "tenders, search only these provinces unless the user names another province."))]


async def run_chat(state: AssistantState) -> AssistantState:
    user_input = state["user_input"]
    chat_history = state.get("chat_history") or []
    # A follow-up depends on the conversation, and a personal question ("what is my company
    # called?") depends on who asks, so a cached answer from someone else would be wrong.
    personal = intent.is_personal(user_input)
    follow_up = _FOLLOW_UP.search(user_input) or intent.is_follow_up(user_input)
    cacheable = not personal and not (chat_history and follow_up)

    # 1. Semantic cache: exact match first, then "same meaning" via vector KNN.
    if cacheable:
        hit = await semantic_cache.lookup(user_input, scope="chat")
        if hit:
            logger.info("Chat cache %s hit (%.3f)", hit["match"], hit["similarity"])
            state["final_response"] = hit["answer"]
            return state

    # 2. Miss: run the agent with the recent conversation (and who the user is, when they ask about themselves).
    from .agent import run_agent
    context = await user_context(state.get("user_email")) if personal else []
    context += await _province_context(state.get("user_email"))
    result = await run_agent(user_input, context + chat_history)
    response_text = result.get("output", "")

    # 3. Cache only answers that are safe to reuse for anyone asking the same thing:
    #    - never a failure (the error would stick after the LLM recovers)
    #    - never an answer built from tool output (live tender data goes stale,
    #      and "tenders in Gauteng" vs "tenders in Limpopo" embed very closely)
    #    The write runs in the background so the reply isn't delayed.
    if cacheable and response_text and not result.get("error") and not result.get("tools_used"):
        _in_background(semantic_cache.store(user_input, response_text, scope="chat"))

    state["final_response"] = response_text
    return state


async def fallback(state: AssistantState) -> AssistantState:
    err = state.get("error")
    if err == "search_failed":
        state["final_response"] = "I couldn't reach the tender database just now. This is usually temporary — please try again in a few seconds."
    elif err == "documents_failed":
        state["final_response"] = "I couldn't fetch those documents. The tender service may be busy — try again, or pick a different tender from your matches."
    elif err == "strategy_failed":
        state["final_response"] = "The strategy engine didn't respond in time. Give it another try in a moment — it usually recovers on the next attempt."
    elif err == "matches_failed":
        state["final_response"] = "I couldn't load your matches just now. Please try again in a moment, or open the Tender Board."
    else:
        state["final_response"] = "Something went wrong on our side. Please try again in a moment."
    state["error"] = None
    return state


def route_after_handler(state: AssistantState) -> Literal["fallback", "end"]:
    return "fallback" if state.get("error") else "end"


def _timed(name: str, fn):
    """Log how long each step takes, so slow parts show up in `docker logs`."""
    @functools.wraps(fn)
    async def wrapper(state):
        started = time.perf_counter()
        try:
            return await fn(state)
        finally:
            elapsed = time.perf_counter() - started
            (logger.warning if elapsed > 10 else logger.info)("step=%s took %.2fs", name, elapsed)
    return wrapper


def build_graph():
    g = StateGraph(AssistantState)

    for name, fn in (("load_hints", load_hints), ("classify", classify_intent), ("clarify", clarify),
                     ("matches", run_matches), ("uploading", run_upload), ("searching", run_search),
                     ("documents", run_documents), ("strategy", run_strategy), ("chat", run_chat),
                     ("fallback", fallback)):
        g.add_node(name, _timed(name, fn))

    g.set_entry_point("load_hints")
    g.add_edge("load_hints", "classify")

    g.add_conditional_edges("classify", route_after_classify, {
        "matches": "matches",
        "uploading": "uploading",
        "searching": "searching",
        "documents": "documents",
        "strategy": "strategy",
        "chat": "chat",
        "clarify": "clarify",
    })

    g.add_edge("clarify", "load_hints")

    for n in ("matches", "searching", "documents", "strategy"):
        g.add_conditional_edges(n, route_after_handler, {
            "fallback": "fallback",
            "end": END,
        })

    g.add_edge("uploading", END)
    g.add_edge("chat", END)
    g.add_edge("fallback", END)

    checkpointer = MemorySaver()
    return g.compile(checkpointer=checkpointer)


def new_message_state(session_id: str, user_input: str, user_email: str | None,
                      chat_history: list) -> AssistantState:
    """Graph input for one chat message.

    The checkpointer keeps each conversation's last state, so the tender number is reset
    here: otherwise an earlier message's tender would be reused.
    """
    return {"session_id": session_id, "user_input": user_input, "user_email": user_email,
            "chat_history": chat_history, "tender_number": None}


_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
        logger.info("LangGraph compiled with checkpointer + loop-back + fallback + cache")
    return _graph