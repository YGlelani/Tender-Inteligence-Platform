"""
Rule-based tender matching with synonym expansion, plus ML category matching.

Vector RAG is available via rank_tenders_hybrid, but the from-pdf endpoint
uses the pure rank_tenders path to guarantee deterministic, fast results.

Category points come from the tender-ml model when it finds a category the company and
tender share (`ml_matches`: tender key -> shared category); otherwise the keyword rule
is used, so the ML can only add points.
"""
import logging
import re
from typing import Iterable

from synonyms import expand_services, expand_industries

logger = logging.getLogger("tender.ai.matcher")

CATEGORY_POINTS_ML = 15
CATEGORY_POINTS_KEYWORD = 5


def tender_key(tender: dict) -> str:
    """Identifies a tender in tender-ml requests: client-api tenders have a number, stored ones an id."""
    return str(tender.get("tender_number") or tender.get("id") or "")


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).lower().strip()


def _keyword_in_text(keyword: str, text: str) -> bool:
    if not keyword or not text:
        return False
    words = [w for w in re.findall(r'\w+', keyword.lower()) if len(w) > 3]
    if not words:
        return keyword.lower() in text
    if keyword.lower() in text:
        return True
    return any(word in text for word in words)


def _category_points(tender: dict, services_expanded, ml_matches: dict | None) -> tuple[int, str | None]:
    """Points for the tender's category.

    A category the ML model says the company and tender share earns the most points.
    Otherwise the keyword rule applies as before, so the ML can only add points.
    """
    shared = (ml_matches or {}).get(tender_key(tender))
    if shared:
        return CATEGORY_POINTS_ML, f"Category matches your business (ML: {shared})"
    category = _normalize(tender.get("category_name"))
    for svc in list(services_expanded)[:10]:
        if category and _keyword_in_text(svc, category):
            return CATEGORY_POINTS_KEYWORD, f"Category aligned with service: {svc}"
    return 0, None


def score_tender(tender: dict, profile: dict, ml_matches: dict | None = None) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    tender_text = _normalize(" ".join(filter(None, [
        tender.get("title", ""),
        tender.get("description", ""),
        tender.get("category_name", ""),
        tender.get("organisation_name", ""),
        tender.get("location", ""),
    ])))

    tender_province = (tender.get("province") or "").strip()

    # 1. Services (with synonyms) — up to 40 points
    services_expanded = expand_services(profile.get("services") or [])
    matched_terms = []
    for term in services_expanded:
        if _keyword_in_text(term, tender_text):
            matched_terms.append(term)
            score += 10
            if len(matched_terms) >= 4:
                break
    if matched_terms:
        reasons.append("Service match: " + ", ".join(matched_terms[:3]))

    # 2. Industries (with synonyms) — up to 20 points
    industries_expanded = expand_industries(profile.get("industries") or [])
    matched_industries = []
    for ind in industries_expanded:
        if _keyword_in_text(ind, tender_text):
            matched_industries.append(ind)
            score += 10
            if len(matched_industries) >= 2:
                break
    if matched_industries:
        reasons.append("Industry match: " + ", ".join(matched_industries[:2]))

    # 3. Province — up to 20 points
    areas = profile.get("service_areas") or []
    if tender_province and any(a.lower() == tender_province.lower() for a in areas):
        score += 20
        reasons.append(f"Province match: {tender_province}")
    elif tender_province in ("National", "") and areas:
        score += 10
        reasons.append("National tender")

    # 4. Category alignment — up to 15 points with the ML model, 5 with the keyword rule
    points, reason = _category_points(tender, services_expanded, ml_matches)
    score += points
    if reason:
        reasons.append(reason)

    return min(score, 100), reasons


def rank_tenders(
    tenders: Iterable[dict],
    profile: dict,
    min_score: int = 10,
    top_n: int = 10,
    ml_matches: dict | None = None,
) -> list[dict]:
    scored = []
    for t in tenders:
        try:
            score, reasons = score_tender(t, profile, ml_matches)
        except Exception:
            continue
        if score < min_score:
            continue
        scored.append({
            "tender_number": t.get("tender_number"),
            "title": t.get("title"),
            "organisation": t.get("organisation_name"),
            "province": t.get("province"),
            "category": t.get("category_name"),
            "closing_date": t.get("closing_date"),
            "published_date": t.get("published_date"),
            "score": score,
            "reasons": reasons,
        })
    scored.sort(key=lambda x: (-x["score"], x.get("closing_date") or ""))
    return scored[:top_n]


async def rank_tenders_hybrid(
    tenders: list[dict],
    profile: dict,
    min_score: int = 10,
    top_n: int = 10,
    vector_top_k: int = 50,
) -> list[dict]:
    """
    Optional vector-RAG wrapper. NOT used by from-pdf — kept for future
    experiments. Always returns a result; falls back on any error.
    """
    try:
        from embeddings import embed
        from vector_store import get_store

        store = get_store()
        if store.size == 0:
            return rank_tenders(tenders, profile, min_score=min_score, top_n=top_n)

        query = " ".join(filter(None, [
            profile.get("business_name", ""),
            " ".join(profile.get("industries") or []),
            " ".join(profile.get("services") or []),
            " ".join(profile.get("service_areas") or []),
        ]))

        try:
            qvec = await embed(query)
            hits = store.search(qvec, k=vector_top_k)
            logger.info("Vector RAG retrieved %d candidates", len(hits))
        except Exception as e:
            logger.warning("Embedding search failed, continuing with rule-based: %s", e)

        return rank_tenders(tenders, profile, min_score=min_score, top_n=top_n)

    except Exception as e:
        logger.warning("Hybrid match failed, falling back: %s", e)
        return rank_tenders(tenders, profile, min_score=min_score, top_n=top_n)