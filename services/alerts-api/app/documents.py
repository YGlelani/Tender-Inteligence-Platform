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


def invalidate_details(user_id):
    _cache.pop(user_id, None)


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
    industries = _list(profile.get("industries"))
    service_areas = _list(profile.get("service_areas"))
    areas = {area.lower() for area in service_areas}
    return {
        "business_name": _text(profile.get("business_name")),
        "registration_number": _text(profile.get("registration_number")),
        "vat_number": _text(profile.get("vat_number")),
        "industry": _text(profile.get("industry") or (industries[0] if industries else "")),
        "province": _text(profile.get("province") or (service_areas[0] if service_areas else "")),
        "bbbee_level": _text(profile.get("bbbee_level")),
        "cidb_grade": _text(profile.get("cidb_grade")),
        "csd_number": _text(profile.get("csd_number")),
        "tender_email": _text(profile.get("contact_email")),
        "phone": _text(profile.get("phone")),
        "business_address": _text(profile.get("business_address") or profile.get("address")),
        "industries": industries[:5],
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
    return with_documents({
        "business_name": details.get("business_name"),
        "registration_number": details.get("registration_number"),
        "vat_number": details.get("vat_number"),
        "industry": details.get("industry"),
        "province": details.get("province"),
        "bbbee_level": details.get("bbbee_level"),
        "cidb_grade": details.get("cidb_grade"),
        "csd_number": details.get("csd_number"),
        "tender_email": details.get("tender_email"),
        "phone": details.get("phone"),
        "business_address": details.get("business_address"),
        "company_description": details.get("description"),
        "services_offered": details.get("services"),
        "provinces": details.get("provinces", []),
        "categories": details.get("industries", []),
        "keywords": [],
    }, details)


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
