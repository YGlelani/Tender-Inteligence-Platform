"""Ask tender-ml which tenders share a likely category with a company.

tender-ml compares the categories the company most likely works in (from its
industry, services, keywords and description) with each tender's saved and
predicted categories. When tender-ml cannot be reached, matching works exactly
as before.
"""
import logging

import httpx

from .config import TENDER_ML_TIMEOUT, TENDER_ML_URL

logger = logging.getLogger("alerts-api")

# Every open tender is scored, so tenders are sent in batches below tender-ml's limit of 5,000.
BATCH_SIZE = 2000
# tender-ml's request limits; staying inside them means a long profile can never be rejected.
MAX_PHRASES, MAX_PHRASE_LENGTH, MAX_TEXT_LENGTH = 200, 1000, 20_000


def _phrases(values) -> list[str]:
    return [str(value)[:MAX_PHRASE_LENGTH] for value in values if value][:MAX_PHRASES]


def _text(value) -> str:
    return str(value or "")[:MAX_TEXT_LENGTH]


def company(profile: dict) -> dict:
    return {
        "industries": _phrases([profile.get("industry"), *(profile.get("document_industries") or [])]),
        "services": _phrases([profile.get("services_offered")]),
        "keywords": _phrases(profile.get("keywords") or []),
        "description": _text(profile.get("company_description")),
    }


def tender_item(tender: dict) -> dict:
    return {
        "id": str(tender["id"]),
        "title": _text(tender.get("title"))[:MAX_PHRASE_LENGTH],
        "description": _text(tender.get("description")),
        "organisation": _text(tender.get("organisation"))[:MAX_PHRASE_LENGTH],
        "category": tender.get("category"),
    }


async def shared_categories(profile: dict, tenders: list[dict]) -> dict[str, str] | None:
    """{tender id: category the company shares}, or None when tender-ml did not answer every batch."""
    matches = {}
    try:
        async with httpx.AsyncClient(timeout=TENDER_ML_TIMEOUT) as client:
            for start in range(0, len(tenders), BATCH_SIZE):
                batch = [tender_item(tender) for tender in tenders[start:start + BATCH_SIZE]]
                resp = await client.post(
                    f"{TENDER_ML_URL}/match-categories", json={"company": company(profile), "tenders": batch}
                )
                resp.raise_for_status()
                matches.update(resp.json()["matches"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        logger.warning("tender-ml unavailable, matching without ML categories: %s", error)
        return None
    return matches
