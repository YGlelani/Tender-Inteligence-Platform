"""
Onboarding agent: turns a user's business profile + compliance documents into
a tender-readiness overview, without any chat.

Flow
  upload  ->  vault (SQLite + disk)  ->  background processing (doc_ai)
          ->  cross-document checks + readiness score + action list
          ->  background insights (AI advice + tender matches)
          ->  GET /agent/overview  (Redis-cached, invalidated on every change)
"""
import asyncio
import difflib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

import httpx

from .cache import get_cache
from .config import ai_service_headers, get_settings
from .doc_ai import (
    DocumentReadError, document_level, extract_document, extract_profile, fetch_website_text,
    llm_json, normalise_url, parse_date, read_file, sha256, validate_document,
)
from .doc_catalog import DOCUMENT_TYPES, PROFILE_WEIGHT, applies_to, get_type
from .vault import get_vault

logger = logging.getLogger(__name__)
settings = get_settings()

OVERVIEW_TTL = 300
MATCHES_TTL = 600
INSIGHTS_MAX_AGE = timedelta(hours=1)

_tasks: set[asyncio.Task] = set()
_insight_locks: dict[str, asyncio.Lock] = {}
_dirty: set[str] = set()


def spawn(coro) -> None:
    """Fire-and-forget a coroutine, keeping a reference so it isn't garbage collected."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _overview_key(email: str) -> str:
    return f"overview:v1:{sha256(email)}"


async def invalidate(email: str) -> None:
    cache = get_cache()
    if cache:
        await cache.delete(_overview_key(email))


# ============================================================
# Business profile
# ============================================================
async def process_profile(email: str, kind: str, data: bytes | None = None, url: str | None = None) -> None:
    vault = get_vault()
    profile, ai_profile_id, error = None, None, None
    try:
        if kind == "website":
            text = await fetch_website_text(url)
            profile = await extract_profile(text, website=url)
        else:
            text, images = await read_file(data)
            profile = await extract_profile(text, images=images or None)
        if not profile.get("business_name"):
            raise DocumentReadError("Couldn't find your business name in the profile.")
        if not profile.get("services") and not profile.get("industries"):
            raise DocumentReadError("Couldn't work out what services the business offers. Try a more detailed profile.")
        ai_profile_id = await register_profile(email, profile)
    except DocumentReadError as e:
        error = str(e)
    except Exception:
        logger.exception("profile processing failed")
        error = "The AI agent couldn't process your profile right now. Please try again in a moment."
    vault.save_profile_result(email, profile, ai_profile_id, error)
    await invalidate(email)
    spawn(refresh_insights(email))


async def register_profile(email: str, profile: dict) -> int | None:
    """Store the profile in the AI service too, so its tender matcher can use it."""
    industries = profile.get("industries") or (profile.get("services") or [])[:3] or ["General services"]
    services = profile.get("services") or industries
    website = profile.get("website")
    payload = {
        "user_email": email,
        "business_name": profile["business_name"][:300],
        "registration_number": profile.get("registration_number"),
        "description": (profile.get("description") or f"{profile['business_name']} — {', '.join(services[:5])}")[:10_000],
        "industries": industries[:30],
        "services": services[:100],
        "service_areas": profile.get("service_areas", [])[:50],
        "certifications": profile.get("certifications", [])[:50],
        "contact_email": profile.get("contact_email"),
        "website": normalise_url(website) if website else None,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(f"{settings.ai_service_url}/api/business-profiles", headers=ai_service_headers(), json=payload)
            if resp.status_code == 422 and payload["website"]:
                payload["website"] = None
                resp = await client.post(f"{settings.ai_service_url}/api/business-profiles", headers=ai_service_headers(), json=payload)
            resp.raise_for_status()
            return resp.json().get("id")
    except Exception as e:
        logger.warning("Could not register profile with AI service: %s", e)
        return None


# ============================================================
# Compliance documents
# ============================================================
async def process_document(email: str, doc_id: str) -> None:
    vault = get_vault()
    doc = vault.get_document(email, doc_id)
    if not doc:
        return
    try:
        with open(doc["path"], "rb") as f:
            data = f.read()
        extraction = await extract_document(doc["doc_type"], data)
        checks = validate_document(doc["doc_type"], extraction)
        vault.save_document_result(doc_id, extraction, checks, None)
    except DocumentReadError as e:
        vault.save_document_result(doc_id, None, [], str(e))
    except Exception:
        logger.exception("document processing failed")
        vault.save_document_result(doc_id, None, [], "The AI agent couldn't process this document. Try again shortly.")
    await invalidate(email)
    spawn(refresh_insights(email))


async def resume_unfinished() -> None:
    """Re-queue work that was interrupted by a restart."""
    vault = get_vault()
    for doc in vault.list_stuck_documents():
        spawn(process_document(doc["user_email"], doc["id"]))
    for prof in vault.list_stuck_profiles():
        if prof and prof["source_kind"] == "website":
            spawn(process_profile(prof["user_email"], "website", url=prof["source_ref"]))
        elif prof and prof.get("file_path"):
            try:
                with open(prof["file_path"], "rb") as f:
                    spawn(process_profile(prof["user_email"], "pdf", data=f.read()))
            except OSError:
                vault.save_profile_result(prof["user_email"], None, None, "Upload interrupted. Please upload again.")


# ============================================================
# Overview
# ============================================================
SENSITIVE = re.compile(r"account_number|id_number|tax_reference", re.I)


def mask(value):
    if isinstance(value, dict):
        return {k: (_mask_str(v) if SENSITIVE.search(k) else mask(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


def _mask_str(v):
    s = re.sub(r"\s", "", str(v or ""))
    return f"•••• {s[-4:]}" if len(s) > 4 else ("••••" if s else v)


def _norm_name(name: str | None) -> str:
    s = (name or "").lower()
    s = re.sub(r"\((pty|rf)\)|\bpty\b|\bltd\b|\blimited\b|\bproprietary\b|\bcc\b|\binc\b|\bnpc\b|\bt/a\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _same_name(a: str, b: str) -> bool:
    a, b = _norm_name(a), _norm_name(b)
    if not a or not b:
        return True
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _best(docs: list[dict]) -> dict | None:
    order = {"verified": 0, "attention": 1, "processing": 2, "invalid": 3, "failed": 4}
    return min(docs, key=lambda d: order.get(d["level"], 9)) if docs else None


def cross_checks(profile: dict | None, by_type: dict[str, list[dict]]) -> list[dict]:
    """Consistency checks across documents — the stuff evaluators disqualify bids for."""
    issues = []

    def fields(key):
        doc = _best([d for d in by_type.get(key, []) if d["status"] == "processed"])
        return (doc.get("extraction") or {}).get("fields") or {} if doc else {}

    cipc = fields("company_registration")
    official = cipc.get("company_name") or (profile or {}).get("business_name")
    source = "CIPC registration" if cipc.get("company_name") else "business profile"

    names = [
        ("tax_compliance", "taxpayer_name"), ("csd_report", "legal_name"), ("bbbee", "entity_name"),
        ("bank_confirmation", "account_holder"), ("bank_statement", "account_holder"),
        ("coida", "employer_name"), ("proof_of_address", "name"),
    ]
    for key, field in names:
        value = fields(key).get(field)
        if official and value and not _same_name(official, value):
            issues.append({
                "level": "warning", "doc_type": key,
                "message": f"Name on the {get_type(key)['label']} (\"{value}\") doesn't match your {source} (\"{official}\").",
            })

    reg = _digits(cipc.get("registration_number"))
    for key, label, value in (
        ("csd_report", "CSD report", fields("csd_report").get("registration_number")),
        (None, "business profile", (profile or {}).get("registration_number")),
    ):
        if reg and _digits(value) and _digits(value) != reg:
            issues.append({
                "level": "warning", "doc_type": key,
                "message": f"Registration number on your {label} differs from CIPC ({cipc.get('registration_number')}).",
            })

    levels = {}
    for key, label, value in (
        ("bbbee", "B-BBEE certificate", fields("bbbee").get("bbbee_level")),
        ("csd_report", "CSD report", fields("csd_report").get("bbbee_level")),
    ):
        if _digits(value):
            levels[label] = _digits(value)
    if len(set(levels.values())) > 1:
        issues.append({
            "level": "warning", "doc_type": "csd_report",
            "message": "B-BBEE level differs between documents ("
                       + ", ".join(f"{k}: level {v}" for k, v in levels.items()) + "). Update CSD.",
        })

    accounts = [_digits(fields(k).get("account_number"))[-4:] for k in ("bank_confirmation", "bank_statement")]
    if all(accounts) and accounts[0] != accounts[1]:
        issues.append({
            "level": "warning", "doc_type": "bank_statement",
            "message": "The bank statement and the bank confirmation letter are for different accounts.",
        })

    directors = cipc.get("directors") if isinstance(cipc.get("directors"), list) else []
    uploaded_ids = {
        _digits(((d.get("extraction") or {}).get("fields") or {}).get("id_number"))
        for d in by_type.get("director_id", []) if d["status"] == "processed"
    }
    uploaded_names = [
        ((d.get("extraction") or {}).get("fields") or {}).get("full_name")
        for d in by_type.get("director_id", []) if d["status"] == "processed"
    ]
    for director in directors:
        if not isinstance(director, dict):
            director = {"name": str(director)}
        name, idn = director.get("name"), _digits(director.get("id_number"))
        has_copy = (idn and idn in uploaded_ids) or any(n and name and _same_name(n, name) for n in uploaded_names)
        if name and not has_copy:
            issues.append({
                "level": "warning", "doc_type": "director_id",
                "message": f"No certified ID copy uploaded for director {name}.",
            })
    return issues


def _public_doc(doc: dict) -> dict:
    ext = doc.get("extraction") or {}
    return {
        "id": doc["id"],
        "filename": doc["filename"],
        "uploaded_at": doc["uploaded_at"],
        "processed_at": doc.get("processed_at"),
        "level": doc["level"],
        "error": doc.get("error"),
        "summary": ext.get("summary"),
        "holder_name": ext.get("holder_name"),
        "expiry_date": ext.get("expiry_date") or (ext.get("fields") or {}).get("expiry_date"),
        "fields": mask(ext.get("fields") or {}),
        "checks": doc.get("checks") or [],
    }


def build_state(email: str) -> dict:
    """Everything deterministic about the user's readiness (no LLM, fast)."""
    vault = get_vault()
    prof_row = vault.get_profile(email)
    profile = (prof_row or {}).get("profile")
    docs = vault.list_documents(email)
    for d in docs:
        d["level"] = document_level(d)

    by_type: dict[str, list[dict]] = {}
    for d in docs:
        by_type.setdefault(d["doc_type"], []).append(d)

    today = date.today()
    checklist, actions, expiring = [], [], []
    total = earned = 0.0

    profile_status = (prof_row or {}).get("status")
    total += PROFILE_WEIGHT
    if profile_status == "ready" or (profile and profile_status == "processing"):
        earned += PROFILE_WEIGHT
    if not prof_row:
        actions.append({"priority": "high", "title": "Add your business profile",
                        "detail": "Upload your company profile PDF or give us your website so the agent can match tenders to you.",
                        "doc_type": "profile"})
    elif profile_status == "failed":
        actions.append({"priority": "high", "title": "Business profile needs another try",
                        "detail": prof_row.get("error") or "Processing failed.", "doc_type": "profile"})

    for t in DOCUMENT_TYPES:
        applicable = applies_to(t, profile)
        items = by_type.get(t["key"], [])
        best = _best(items)
        level = best["level"] if best else "missing"
        if applicable and t["weight"]:
            total += t["weight"]
            earned += t["weight"] * {"verified": 1, "attention": 0.6}.get(level, 0)

        checklist.append({
            "key": t["key"], "label": t["label"], "hint": t["hint"], "requirement": t["requirement"],
            "multiple": t["multiple"], "applies": applicable, "level": level,
            "documents": [_public_doc(d) for d in items],
        })

        for d in items:
            exp = parse_date((d.get("extraction") or {}).get("expiry_date")
                             or ((d.get("extraction") or {}).get("fields") or {}).get("expiry_date"))
            if exp and exp <= today + timedelta(days=60):
                expiring.append({"doc_type": t["key"], "label": t["label"], "expiry_date": exp.isoformat(),
                                 "days_left": (exp - today).days})

        if not applicable:
            continue
        if level == "missing" and t["requirement"] in ("required", "sector"):
            actions.append({
                "priority": "high" if t["requirement"] == "required" else "medium",
                "title": f"Upload your {t['label']}",
                "detail": t["hint"] if t["requirement"] == "required"
                else f"{t['hint']} Your industry usually needs this.",
                "doc_type": t["key"],
            })
        elif level == "missing" and t["requirement"] == "recommended":
            actions.append({"priority": "low", "title": f"Add your {t['label']}", "detail": t["hint"], "doc_type": t["key"]})
        elif level in ("invalid", "failed"):
            first = next((c["message"] for c in best.get("checks") or [] if c["level"] == "error"), best.get("error"))
            actions.append({"priority": "high", "title": f"Fix your {t['label']}", "detail": first or "", "doc_type": t["key"]})
        elif level == "attention":
            first = next((c["message"] for c in best.get("checks") or [] if c["level"] == "warning"), "")
            actions.append({"priority": "medium", "title": f"Check your {t['label']}", "detail": first, "doc_type": t["key"]})

    issues = cross_checks(profile, by_type)
    for issue in issues:
        actions.append({"priority": "medium", "title": "Documents don't agree", "detail": issue["message"],
                        "doc_type": issue.get("doc_type")})

    score = round(100 * earned / total) if total else 0
    score = max(0, score - 3 * len(issues))
    order = {"high": 0, "medium": 1, "low": 2}
    actions.sort(key=lambda a: order[a["priority"]])
    expiring.sort(key=lambda e: e["days_left"])

    counted = [c for c in checklist if c["applies"] and c["requirement"] in ("required", "sector")]
    return {
        "onboarding_needed": not prof_row and not docs,
        "processing": profile_status == "processing" or any(d["level"] == "processing" for d in docs),
        "readiness": {
            "score": score,
            "label": "Tender ready" if score >= 85 else "Almost there" if score >= 60 else "Getting started",
            "verified": sum(c["level"] == "verified" for c in counted),
            "attention": sum(c["level"] in ("attention", "invalid", "failed") for c in counted),
            "missing": sum(c["level"] == "missing" for c in counted),
            "required_total": len(counted),
        },
        "profile": None if not prof_row else {
            "status": profile_status,
            "source_kind": prof_row["source_kind"],
            "source_ref": prof_row["source_ref"],
            "error": prof_row.get("error"),
            "ai_profile_id": prof_row.get("ai_profile_id"),
            "updated_at": prof_row["updated_at"],
            **(profile or {}),
        },
        "checklist": checklist,
        "cross_checks": issues,
        "actions": actions,
        "expiring": expiring,
    }


async def get_overview(email: str) -> dict:
    cache = get_cache()
    key = _overview_key(email)
    if cache and (hit := await cache.get(key)):
        return hit

    state = build_state(email)
    insights = get_vault().get_insights(email) or {}
    state.update({
        "ai_summary": insights.get("summary"),
        "ai_advice": insights.get("advice", []),
        "matches": insights.get("matches", []),
        "tenders_scanned": insights.get("tenders_scanned"),
        "insights_updated_at": insights.get("updated_at"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })

    stale = not insights or (
        datetime.now(timezone.utc) - datetime.fromisoformat(insights["updated_at"]) > INSIGHTS_MAX_AGE
    )
    if stale and not state["onboarding_needed"] and not state["processing"]:
        spawn(refresh_insights(email, changed=False))

    # Don't cache while documents are still being processed — the page is polling.
    if cache and not state["processing"]:
        await cache.set(key, state, ttl=OVERVIEW_TTL)
    return state


# ============================================================
# Insights: tender matches + AI advice (background, cached)
# ============================================================
ADVICE_SYSTEM = """You are a senior South African tender consultant reviewing a supplier's readiness.
You receive their business profile, the status of their compliance documents, and tenders that match them.
Return ONE JSON object: {"summary": "1-2 sentences on how ready they are to bid and the single most important thing to do",
"advice": [{"title": "short imperative", "detail": "1-2 practical sentences"}]}.
Give 3-5 advice items specific to THIS business: missing sector registrations (CIDB, PSIRA, professional bodies),
how their B-BBEE level affects preference points (80/20 and 90/10), which matched tenders to prioritise and why,
documents to refresh before upcoming closing dates, and how to strengthen their profile for evaluators.
Do not repeat generic upload instructions for documents already verified. Never invent facts about the business."""


async def fetch_matches(ai_profile_id: int) -> dict:
    cache = get_cache()
    key = f"matches:v1:{ai_profile_id}"
    if cache and (hit := await cache.get(key)):
        return hit
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{settings.ai_service_url}/api/business-profiles/{ai_profile_id}/matches", headers=ai_service_headers(),
                                params={"top_n": 6})
        resp.raise_for_status()
        result = resp.json()
    if cache:
        await cache.set(key, result, ttl=MATCHES_TTL)
    return result


async def refresh_insights(email: str, changed: bool = True) -> None:
    """Recompute matches + AI advice. `changed=False` is a periodic refresh, not a new upload."""
    if changed:
        _dirty.add(email)
    lock = _insight_locks.setdefault(email, asyncio.Lock())
    if lock.locked():
        return  # the running refresh loops again if anything changed meanwhile
    async with lock:
        while True:
            _dirty.discard(email)
            await asyncio.sleep(2)  # let a burst of uploads settle first
            try:
                await _refresh_once(email)
            except Exception:
                logger.exception("insight refresh failed")
            if email not in _dirty:
                break


async def _refresh_once(email: str) -> None:
    vault = get_vault()
    state = build_state(email)
    if state["processing"] or state["onboarding_needed"]:
        return
    profile = state["profile"] or {}

    ai_profile_id = profile.get("ai_profile_id")
    if profile.get("business_name") and not ai_profile_id and profile.get("status") == "ready":
        ai_profile_id = await register_profile(email, {k: profile.get(k) for k in profile})
        if ai_profile_id:
            vault.save_profile_result(email, None, ai_profile_id, None)

    matches, scanned = [], None
    if ai_profile_id:
        try:
            m = await fetch_matches(ai_profile_id)
            matches, scanned = m.get("top_matches", []), m.get("tenders_scanned")
        except Exception as e:
            logger.warning("matches unavailable: %s", e)

    advice_input = {
        "profile": {k: profile.get(k) for k in (
            "business_name", "description", "industries", "services", "service_areas",
            "certifications", "bbbee_level", "cidb_grading", "employees", "year_established")},
        "documents": [
            {"document": c["label"], "requirement": c["requirement"], "status": c["level"],
             "problems": [x["message"] for d in c["documents"] for x in d["checks"]][:3]}
            for c in state["checklist"] if c["applies"]
        ],
        "cross_document_issues": [i["message"] for i in state["cross_checks"]],
        "readiness_score": state["readiness"]["score"],
        "matched_tenders": [
            {k: m.get(k) for k in ("title", "organisation", "province", "category", "closing_date", "score")}
            for m in matches[:6]
        ],
        "today": date.today().isoformat(),
    }
    state_hash = sha256(json.dumps(advice_input, sort_keys=True, default=str))
    previous = vault.get_insights(email) or {}

    summary, advice = previous.get("summary"), previous.get("advice", [])
    saved_hash = previous.get("state_hash")
    if saved_hash != state_hash:
        cache = get_cache()
        akey = f"advice:v1:{state_hash}"
        cached = await cache.get(akey) if cache else None
        if cached:
            summary, advice, saved_hash = cached.get("summary"), cached.get("advice", []), state_hash
        else:
            try:
                result = await llm_json(ADVICE_SYSTEM, json.dumps(advice_input, default=str))
                new_advice = [
                    {"title": str(a.get("title", ""))[:120], "detail": str(a.get("detail", ""))[:500]}
                    for a in (result.get("advice") or []) if isinstance(a, dict) and a.get("title")
                ][:5]
                if not new_advice:
                    raise ValueError("model returned no advice")
                summary, advice, saved_hash = str(result.get("summary") or "")[:600] or None, new_advice, state_hash
                if cache:
                    await cache.set(akey, {"summary": summary, "advice": advice}, ttl=60 * 60 * 24 * 7)
            except Exception as e:
                # Keep the previous hash so the next refresh retries the advice.
                logger.warning("AI advice failed: %s", e)

    vault.save_insights(email, saved_hash, {
        "summary": summary, "advice": advice, "matches": matches, "tenders_scanned": scanned,
    })
    await invalidate(email)
