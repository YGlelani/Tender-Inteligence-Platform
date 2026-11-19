"""
The provinces a signed-in user's tender searches are limited to.

A chat search that names no province uses the same provinces as the user's matches:
the provinces on their Business Profile in Smart Alerts or, when they have no Business
Profile, the service areas of their uploaded business profile. National tenders are always
included. An empty list means no limit (the user has no provinces set).
"""
import logging

import httpx

from .config import get_settings
from .matches import find_user_profile
from .tender_index import detect_province

logger = logging.getLogger(__name__)
settings = get_settings()

ALERTS_TIMEOUT_SECONDS = 10


async def business_profile_provinces(token: str) -> list[str] | None:
    """The provinces on the user's Business Profile, or None when they have none or Smart Alerts is down."""
    try:
        async with httpx.AsyncClient(timeout=ALERTS_TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{settings.alerts_api_url}/profile",
                                    headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        provinces = resp.json().get("provinces")
    except (httpx.HTTPError, ValueError, AttributeError) as error:
        logger.warning("Business Profile provinces unavailable: %s", error)
        return None
    return list(provinces or [])


async def profile_provinces(email: str | None, token: str | None) -> list[str]:
    """The user's provinces as search filters ("gauteng", ..., "national"), or [] for anywhere."""
    if not email:
        return []
    names = await business_profile_provinces(token) if token else None
    if names is None:
        try:
            profile = await find_user_profile(email)
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Uploaded profile unavailable for province filtering: %s", error)
            profile = None
        names = (profile or {}).get("service_areas") or []
    provinces = []
    for name in names:
        province = detect_province(str(name))
        if province and province not in provinces:
            provinces.append(province)
    if provinces and "national" not in provinces:
        provinces.append("national")
    return provinces
