import logging
import time

import httpx

from .config import AGENT_URL

logger = logging.getLogger("alerts-api")

PROVINCES = [
    "Eastern Cape", "Free State", "Gauteng", "KwaZulu-Natal", "Limpopo",
    "Mpumalanga", "Northern Cape", "North West", "Western Cape",
]
CACHE_SECONDS = 600
FAILURE_SECONDS = 60
EMPTY = {"industries": [], "keywords": [], "services": "", "description": "", "provinces": []}

_cache = {}


def _text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(filter(None, (_text(item) for item in value)))
    if isinstance(value, dict):
        return ", ".join(filter(None, (_text(item) for item in value.values())))
    return str(value).strip()


def _list(value):
    return [text for text in (_text(item) for item in (value if isinstance(value, list) else [])) if text]


def details_from_overview(overview):
    profile = (overview or {}).get("profile") or {}
    if not profile or profile.get("status") == "failed" or not profile.get("business_name"):
        return dict(EMPTY)
    services = _list(profile.get("services"))
    areas = {area.lower() for area in _list(profile.get("service_areas"))}
    return {
        "industries": _list(profile.get("industries"))[:5],
        "keywords": services[:10],
        "services": ", ".join(services),
        "description": _text(profile.get("description")),
        "provinces": [province for province in PROVINCES if province.lower() in areas],
    }


def cached_details(user_id):
    entry = _cache.get(user_id)
    return entry[1] if entry else dict(EMPTY)


async def fetch_details(user_id, token):
    entry = _cache.get(user_id)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            response = await client.get(
                f"{AGENT_URL}/agent/overview",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            details = details_from_overview(response.json())
        _cache[user_id] = (time.monotonic() + CACHE_SECONDS, details)
        return details
    # Network/HTTP errors, a malformed AGENT_URL, invalid JSON (ValueError),
    # or JSON that isn't the expected object shape (AttributeError).
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, AttributeError) as error:
        logger.warning("Business documents profile unavailable for user %s: %s", user_id, error)
        previous = entry[1] if entry else dict(EMPTY)
        _cache[user_id] = (time.monotonic() + FAILURE_SECONDS, previous)
        return previous


def profile_from_documents(details):
    """A profile built only from uploaded business documents, for users without a Business Profile.

    Document provinces filter tenders the same way Business Profile provinces do.
    """
    if not (details.get("industries") or details.get("keywords") or details.get("services")):
        return None
    return with_documents({"provinces": details.get("provinces", []), "keywords": []}, details)


def with_documents(profile, details):
    if not profile:
        return profile
    merged = dict(profile)
    own = {str(keyword).strip().lower() for keyword in (profile.get("keywords") or [])}
    merged["document_keywords"] = [
        keyword for keyword in details.get("keywords", []) if keyword.lower() not in own
    ]
    merged["document_industries"] = details.get("industries", [])
    merged["services_offered"] = ", ".join(
        filter(None, [profile.get("services_offered") or "", details.get("services", "")])
    )
    merged["company_description"] = " ".join(
        filter(None, [profile.get("company_description") or "", details.get("description", "")])
    )
    return merged
