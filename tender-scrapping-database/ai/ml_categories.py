"""
Ask tender-ml which tenders share a likely category with a company.

tender-ml compares the categories the company most likely works in (from its
industries, services and description) with each tender's saved and predicted
categories. When tender-ml cannot be reached the matcher falls back to its
keyword category rule, so matching never breaks because of the ML service.
"""
import logging
import os

import httpx

from matcher import tender_key

logger = logging.getLogger("tender.ai.ml_categories")

TENDER_ML_URL = os.getenv("TENDER_ML_URL", "http://tender-ml:9004").rstrip("/")
TIMEOUT_SECONDS = float(os.getenv("TENDER_ML_TIMEOUT", "5"))
# tender-ml's request limits; staying inside them means a long profile can never be rejected.
MAX_PHRASES, MAX_PHRASE_LENGTH, MAX_TEXT_LENGTH = 200, 1000, 20_000


def _phrases(values) -> list[str]:
    return [str(value)[:MAX_PHRASE_LENGTH] for value in (values or [])][:MAX_PHRASES]


def request_body(profile: dict, tenders: list[dict]) -> dict:
    return {
        "company": {
            "industries": _phrases(profile.get("industries")),
            "services": _phrases(profile.get("services")),
            "description": str(profile.get("description") or "")[:MAX_TEXT_LENGTH],
        },
        "tenders": [
            {
                "id": tender_key(t),
                "title": str(t.get("title") or "")[:MAX_PHRASE_LENGTH],
                "description": str(t.get("description") or "")[:MAX_TEXT_LENGTH],
                "organisation": str(t.get("organisation_name") or t.get("organisation") or "")[:MAX_PHRASE_LENGTH],
                "category": t.get("category_name") or t.get("category"),
            }
            for t in tenders if tender_key(t)
        ],
    }


async def shared_categories(profile: dict, tenders: list[dict]) -> dict[str, str] | None:
    """{tender key: category the company shares}, or None when tender-ml did not answer."""
    if not tenders:
        return {}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{TENDER_ML_URL}/match-categories", json=request_body(profile, tenders))
            resp.raise_for_status()
            return resp.json()["matches"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        logger.warning("tender-ml unavailable, using the keyword category rule: %s", error)
        return None
