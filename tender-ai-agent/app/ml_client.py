"""
Client for tender-ml, the service that predicts a tender category from text.

The chatbot must work exactly as before when tender-ml is down or slow, so a
failed call returns None instead of raising.
"""
import logging

import httpx

from .config import get_settings
from .upstream import post_json

logger = logging.getLogger(__name__)
settings = get_settings()

# A search is only narrowed to the predicted category at this confidence or above.
# tender-ml's calibration report shows predictions this sure are right about 80% of the time,
# and a wrong category would hide relevant tenders, so the bar is higher than tender-ml's own 50%.
MIN_SEARCH_CONFIDENCE = 0.7


async def predict_category(text: str) -> dict | None:
    """{"category": ..., "explanation": [...]} when the model is at least 70% sure, otherwise None."""
    if not text.strip():
        return None
    try:
        prediction = await post_json(
            f"{settings.tender_ml_url}/predict", {"title": text[:1000]}, timeout=settings.tender_ml_timeout
        )
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("tender-ml unavailable, searching without a predicted category: %r", error)
        return None
    try:
        best = prediction["suggestions"][0]
        confident = best["probability"] >= MIN_SEARCH_CONFIDENCE
    except (KeyError, IndexError, TypeError):
        logger.warning("tender-ml returned an unexpected answer: %r", prediction)
        return None
    if not confident:
        return None
    return {"category": best["category"], "explanation": prediction.get("explanation") or []}
